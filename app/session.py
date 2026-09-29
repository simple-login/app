import uuid
from time import time
from typing import Optional

import flask
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

SUDO_TIME_KEY = "sudo_time"
# Id of the user the sudo mode was granted to. Sudo mode is only valid for that
# user, so a session cannot be used to approve a sensitive action performed as
# another principal.
SUDO_USER_ID_KEY = "sudo_user_id"


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
        # Drop every value, otherwise leftovers like the sudo mode state would
        # be carried over to the session created for the next request
        session.clear()
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
            except Exception:
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
        samesite = self.get_cookie_samesite(app)
        val = pickle.dumps(dict(session))
        ttl = int(app.permanent_session_lifetime.total_seconds())
        # Only 5 minutes for non-authenticated sessions.
        # We need to keep the non-authenticated ones because the csrf token is stored in the session.
        if "_user_id" not in session:
            ttl = 300
        self._redis_w.setex(
            name=self._get_key(session.session_id),
            value=val,
            time=ttl,
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
            samesite=samesite,
        )


def logout_session():
    logout_user()
    purge_fn = getattr(current_app.session_interface, "purge_session", None)
    if callable(purge_fn):
        purge_fn(session)
    else:
        session.clear()


def set_session_sudo_mode(user_id: int):
    """Grant sudo mode to the session, bound to the user it was granted for"""
    session[SUDO_TIME_KEY] = int(time())
    session[SUDO_USER_ID_KEY] = user_id


def clear_session_sudo_mode():
    session.pop(SUDO_TIME_KEY, None)
    session.pop(SUDO_USER_ID_KEY, None)


def is_session_sudo_mode_active(user_id: int, max_age_seconds: int) -> bool:
    """Whether the session holds a fresh sudo mode granted to user_id.

    The user id has to match: a session cannot approve a sensitive action
    performed as another user.
    """
    sudo_time = session.get(SUDO_TIME_KEY)
    if sudo_time is None:
        return False
    if session.get(SUDO_USER_ID_KEY) != user_id:
        return False
    return (time() - int(sudo_time)) <= max_age_seconds
