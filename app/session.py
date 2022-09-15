import uuid

import flask
import redis

try:
    import cPickle as pickle
except ImportError:
    import pickle

import itsdangerous
from flask.sessions import SessionMixin, SessionInterface
from werkzeug.datastructures import CallbackDict

SESSION_PREFIX = 'session'


class ServerSession(CallbackDict, SessionMixin):

    def __init__(self, initial=None, sid=None):
        def on_update(self):
            self.modified = True

        CallbackDict.__init__(self, initial, on_update)
        self.sid = sid
        self.modified = False


class RedisSessionStore(SessionInterface):

    def __init__(self, redis, app):
        self._redis = redis
        self._app = app

    def _get_signer(self, app) -> itsdangerous.Signer:
        return itsdangerous.Signer(app.secret_key, salt='session', key_derivation='hmac')

    def _get_key(self, sid: str) -> str:
        return f"{SESSION_PREFIX}:{sid}"

    def open_session(self, app: flask.Flask, request: flask.Request):
        unverified_sid = request.cookies.get(app.session_cookie_name)
        if not unverified_sid:
            unverified_sid = str(uuid.uuid4())
            return ServerSession(sid=unverified_sid)
        signer = self._get_signer(app)
        try:
            sid_as_bytes = signer.unsign(unverified_sid)
            sid = sid_as_bytes.decode()
        except itsdangerous.BadSignature:
            unverified_sid = str(uuid.uuid4())
            return ServerSession(sid=unverified_sid)

        val = self._redis.get(self._get_key(sid))
        if val is not None:
            try:
                data = pickle.loads(val)
                return ServerSession(data, sid=sid)
            except:
                pass
        return ServerSession(sid=unverified_sid)

    def save_session(self, app: flask.Flask, session: ServerSession, response: flask.Response):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        httponly = self.get_cookie_httponly(app)
        secure = self.get_cookie_secure(app)
        expires = self.get_expiration_time(app, session)
        val = pickle.dumps(dict(session))
        self._redis.setex(name=self._get_key(session.sid), value=val, time=int(app.permanent_session_lifetime.total_seconds()))
        session_id = self._get_signer(app).sign(itsdangerous.want_bytes(session.sid))
        response.set_cookie(app.session_cookie_name, session_id,
                            expires=expires, httponly=httponly,
                            domain=domain, path=path, secure=secure)

def set_redis_session(app: flask.Flask, redis_url: str):
    app.session_interface = RedisSessionStore(redis.from_url(redis_url), app)