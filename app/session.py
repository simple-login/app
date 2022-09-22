import uuid
from typing import Optional

import flask
import redis
from flask import current_app, session
from flask_login import logout_user

try:
    import cPickle as pickle
except ImportError:
    import pickle

import itsdangerous
import urllib.parse
from flask.sessions import SessionMixin, SessionInterface
from werkzeug.datastructures import CallbackDict

SESSION_PREFIX = "session"


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, session_id=None):
        def on_update(self):
            self.modified = True

        super(ServerSession, self).__init__(initial, on_update)
        self.session_id = session_id
        self.modified = False


class RedisSessionStore(SessionInterface):
    def __init__(self, redis_w, redis_r, app):
        self._redis_w = redis_w
        self._redis_r = redis_r
        self._app = app

    @classmethod
    def _get_signer(cls, app) -> itsdangerous.Signer:
        return itsdangerous.Signer(
            app.secret_key, salt="session", key_derivation="hmac"
        )

    @classmethod
    def _get_key(cls, session_Id: str) -> str:
        return f"{SESSION_PREFIX}:{session_Id}"

    @classmethod
    def extract_and_validate_session_id(
        cls, app: flask.Flask, request: flask.Request
    ) -> Optional[str]:
        unverified_session_Id = request.cookies.get(app.session_cookie_name)
        if not unverified_session_Id:
            return None
        signer = cls._get_signer(app)
        try:
            sid_as_bytes = signer.unsign(unverified_session_Id)
            return sid_as_bytes.decode()
        except itsdangerous.BadSignature:
            return None

    def purge_session(self, session: ServerSession):
        try:
            self._redis_w.delete(self._get_key(session.session_id))
            session.session_id = str(uuid.uuid4())
        except AttributeError:
            pass

    def open_session(self, app: flask.Flask, request: flask.Request):
        session_id = self.extract_and_validate_session_id(app, request)
        if not session_id:
            return ServerSession(session_id=str(uuid.uuid4()))

        val = self._redis_r.get(self._get_key(session_id))
        if val is not None:
            try:
                data = pickle.loads(val)
                return ServerSession(data, session_id=session_id)
            except:
                pass
        return ServerSession(session_id=str(uuid.uuid4()))

    def save_session(
        self, app: flask.Flask, session: ServerSession, response: flask.Response
    ):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        expires = self.get_expiration_time(app, session)
        val = pickle.dumps(dict(session))
        self._redis_w.setex(
            name=self._get_key(session.session_id),
            value=val,
            time=int(app.permanent_session_lifetime.total_seconds()),
        )
        signed_session_id = self._get_signer(app).sign(
            itsdangerous.want_bytes(session.session_id)
        )
        response.set_cookie(
            app.session_cookie_name,
            signed_session_id,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
        )


def _get_redis_sessionstore(app: flask.Flask, redis_url: str) -> RedisSessionStore:
    redis_conn = redis.from_url(redis_url)
    return RedisSessionStore(redis_conn, redis_conn, app)


def _get_redis_sentinel_sessionstore(
    app: flask.Flask, redis_url: str
) -> RedisSessionStore:
    # This code has been taken from the flask rate limiter library
    parsed = urllib.parse.urlparse(redis_url)
    sentinel_configuration = []
    password = None
    if parsed.password:
        password = parsed.password
    for loc in parsed.netloc[parsed.netloc.find("@") + 1 :].split(","):
        host, port = loc.split(":")
        sentinel_configuration.append((host, int(port)))
    service_name = parsed.path.replace("/", "")
    if not service_name:
        raise RuntimeError(
            f"Cannot connect to Redis Sentinel: service_name was not provided (the portion after /)"
        )

    sentinel = redis.Sentinel(
        sentinel_configuration, password=password, socket_timeout=0.2
    )
    master = sentinel.master_for(service_name)
    replica = sentinel.slave_for(service_name)

    return RedisSessionStore(master, replica, app)


def set_redis_session(app: flask.Flask, redis_url: str):
    if redis_url.startswith("redis://"):
        app.session_interface = _get_redis_sessionstore(app, redis_url)
    elif redis_url.startswith("redis+sentinel://"):
        app.session_interface = _get_redis_sentinel_sessionstore(app, redis_url)
    else:
        raise RuntimeError(
            f"Tried to set_redis_session with an invalid redis url: ${redis_url}"
        )


def logout_session():
    logout_user()
    purge_fn = getattr(current_app.session_interface, "purge_session", None)
    if callable(purge_fn):
        purge_fn(session)
