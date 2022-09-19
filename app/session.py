import uuid
from typing import Optional

import flask
import redis

try:
    import cPickle as pickle
except ImportError:
    import pickle

import itsdangerous
from flask.sessions import SessionMixin, SessionInterface
from werkzeug.datastructures import CallbackDict

SESSION_PREFIX = "session"


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, session_Id=None):
        def on_update(self):
            self.modified = True

        super(ServerSession, self).__init__(initial, on_update)
        self.session_id = session_Id
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

    def open_session(self, app: flask.Flask, request: flask.Request):
        unverified_session_Id = request.cookies.get(app.session_cookie_name)
        if not unverified_session_Id:
            unverified_session_Id = str(uuid.uuid4())
            return ServerSession(session_Id=unverified_session_Id)
        signer = self._get_signer(app)
        try:
            sid_as_bytes = signer.unsign(unverified_session_Id)
            session_id = sid_as_bytes.decode()
        except itsdangerous.BadSignature:
            unverified_session_Id = str(uuid.uuid4())
            return ServerSession(session_Id=unverified_session_Id)

        val = self._redis.get(self._get_key(session_id))
        if val is not None:
            try:
                data = pickle.loads(val)
                return ServerSession(data, session_Id=session_id)
            except:
                pass
        return ServerSession(session_Id=unverified_session_Id)

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
        session_id = self._get_signer(app).sign(
            itsdangerous.want_bytes(session.session_id)
        )
        response.set_cookie(
            app.session_cookie_name,
            session_id,
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
        )


def set_redis_session(app: flask.Flask, redis_url: str):
    app.session_interface = RedisSessionStore(redis.from_url(redis_url), app)
