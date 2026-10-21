"""CSRF enforcement on the custom (non-ModelView) admin views.

The hand-written admin views (email search, custom domain search) act directly
on ``request.form`` and had no CSRF token check at all. This test runs with
``WTF_CSRF_ENABLED`` turned back on - the suite-wide default disables it - and
asserts that a POST without a valid token is refused before the handler runs.
"""

from time import time
from typing import Generator, Optional

import pytest
from flask import url_for

from tests.conftest import app
from tests.utils import random_token
from app.db import Session
from app.models import User


CSRF_WARNING_MESSAGE = "Invalid request"


def _login(flask_client, user: User) -> None:
    """Sign in over HTTP with CSRF validation off.

    The login form needs a token of its own once validation is on, and a failed
    login does not fail loudly - it answers 200 by re-rendering the form - so
    the session check below is what proves the sign-in really happened.
    Any previous sign-in is dropped first: the login view redirects an already
    authenticated client instead of switching accounts.
    """
    with _csrf_enabled(False):
        flask_client.get(url_for("auth.logout"))
        _post_login(flask_client, user)


def _post_login(flask_client, user: User) -> None:
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    with flask_client.session_transaction() as sess:
        assert sess.get("_user_id") is not None, "login did not produce a session"


class _csrf_enabled:
    """Context manager restoring the previous ``WTF_CSRF_ENABLED`` on exit.

    The suite disables CSRF globally (tests/conftest.py); this test needs it
    back on, and a sign-in needs it pinned off, because a login attempted with
    validation on does not fail loudly - it re-renders the login page.
    """

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def __enter__(self):
        self.previous = app.config.get("WTF_CSRF_ENABLED")
        app.config["WTF_CSRF_ENABLED"] = self.enabled
        return self

    def __exit__(self, *exc_info):
        app.config["WTF_CSRF_ENABLED"] = self.previous
        return False


def create_admin_user(email: Optional[str] = None) -> User:
    user = User.create(
        email=email or f"admin_{random_token(10)}@mailbox.lan",
        password="password",
        name="Admin User",
        activated=True,
        is_admin=True,
        flush=True,
    )
    Session.flush()
    return user


@pytest.fixture
def csrf_admin(flask_client) -> Generator[User, None, None]:
    """An admin signed in over HTTP, with CSRF enforcement switched on.

    The flag is flipped on after signing in - a login attempted with validation
    on does not fail loudly, it re-renders the login page, and the test would
    silently act as an anonymous visitor - so the sign-in helper pins the flag
    off for its own duration.
    """
    with _csrf_enabled(True):
        admin_user = create_admin_user()
        Session.commit()
        _login(flask_client, admin_user)
        _unlock_admin_panel(flask_client)
        yield admin_user


def _unlock_admin_panel(flask_client) -> None:
    """Replay what dashboard/views/enter_admin.py stores after a key ceremony.

    ``ADMIN_FIDO_REQUIRED`` is read from ``app.config`` at request time, so
    patching it works even though ``enter_admin`` itself imported the constant
    at import time.
    """
    with flask_client.session_transaction() as sess:
        sess["admin_time"] = int(time())
        sess["admin_hardware_auth"] = True


def flash_messages(client) -> str:
    """Flash messages queued in the session of ``client``.

    Read straight from the session because Flask pops them on the next render,
    which would make the assertion depend on whether the page template happens
    to display them.
    """
    with client.session_transaction() as sess:
        return "; ".join(str(message[1]) for message in sess.get("_flashes", []))


def test_post_without_csrf_token_is_rejected(csrf_admin, flask_client):
    """A POST to the email-search route without a CSRF token is refused by the
    guard - redirected to the view index carrying the "Invalid request" warning
    - instead of reaching the handler."""
    url = url_for("admin.email_search.index")

    r = flask_client.post(url, data={"query": "someone@example.com"})

    assert r.status_code == 302
    assert url_for("admin.email_search.index") in r.headers["Location"]
    assert CSRF_WARNING_MESSAGE in flash_messages(flask_client)
