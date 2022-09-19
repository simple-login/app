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
    def __init__(self, redis, app):
        self._redis = redis
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
            self._redis.delete(self._get_key(session.session_id))
            session.session_id = str(uuid.uuid4())
        except AttributeError:
            pass

    def open_session(self, app: flask.Flask, request: flask.Request):
        session_id = self.extract_and_validate_session_id(app, request)
        if not session_id:
            return ServerSession(session_id=str(uuid.uuid4()))

        val = self._redis.get(self._get_key(session_id))
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
        self._redis.setex(
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


def set_redis_session(app: flask.Flask, redis_url: str):
    app.session_interface = RedisSessionStore(redis.from_url(redis_url), app)


def logout_session():
    logout_user()
    purge_fn = getattr(current_app.session_interface, "purge_session", None)
    if callable(purge_fn):
        purge_fn(session)
