"""Changing the second factor must revoke trusted-browser tokens (SECBTY-2597).

A "remember this browser" cookie minted before a second-factor change used to
keep skipping the new factor for the rest of its 30-day window. The four
screens that change a second factor now delete MfaBrowser rows, the way
reset_password.py and change_email.py already did.
"""

import uuid
from time import time
from unittest.mock import MagicMock, patch

import pyotp
from flask import url_for

from app.db import Session
from app.models import Fido, MfaBrowser
from tests.utils import create_new_user, enter_sudo_mode


def _set_cookie(client, key, value):
    try:
        client.set_cookie("sl.lan", key, value)  # werkzeug < 2.3
    except TypeError:
        client.set_cookie(key, value, domain="sl.lan")  # werkzeug >= 2.3


def _login(flask_client, user):
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )
    assert b"/auth/logout" in r.data


def _enable_totp(flask_client, user) -> str:
    enter_sudo_mode(flask_client, user)
    r = flask_client.get(url_for("dashboard.mfa_setup"))
    assert r.status_code == 200
    secret = user.otp_secret
    assert secret
    token = pyotp.TOTP(secret).now()
    r = flask_client.post(
        url_for("dashboard.mfa_setup"), data={"token": token}, follow_redirects=True
    )
    assert r.status_code == 200
    assert user.enable_otp is True
    return secret


def _mint_trusted_browser_via_endpoints(flask_client, user, secret) -> str:
    """Log out, log in with the password, pass MFA with 'remember this browser'."""
    flask_client.get(url_for("auth.logout"), follow_redirects=True)
    r = flask_client.post(
        url_for("auth.login"), data={"email": user.email, "password": "password"}
    )
    assert r.status_code == 302 and "/auth/mfa" in r.location
    # a token from the NEXT period: mfa.py rejects token == user.last_otp
    tok = pyotp.TOTP(secret).at(int(time()) + 30)
    r = flask_client.post(url_for("auth.mfa"), data={"token": tok, "remember": "y"})
    assert r.status_code == 302
    rows = MfaBrowser.filter_by(user_id=user.id).all()
    assert len(rows) == 1
    return rows[0].token


def _mint_trusted_browser_directly(user) -> str:
    browser = MfaBrowser.create_new(user=user)
    Session.commit()
    return browser.token


def _register_hardware_key(user) -> Fido:
    user.fido_uuid = str(uuid.uuid4())
    Session.commit()  # fido.uuid has an FK on users.fido_uuid
    key = Fido.create(
        credential_id="cred-" + uuid.uuid4().hex,
        uuid=user.fido_uuid,
        public_key="pk-" + uuid.uuid4().hex,
        sign_count=0,
        name="Hardware Key",
        user_id=user.id,
        flush=True,
    )
    Session.commit()
    return key


def _login_following_gates(client, user):
    """Password login, following redirects manually. Returns visited paths."""
    r = client.post(
        url_for("auth.login"), data={"email": user.email, "password": "password"}
    )
    visited = ["/auth/login"]
    while r.status_code in (301, 302, 303, 307, 308) and len(visited) < 10:
        from urllib.parse import urlparse

        path = urlparse(r.location).path
        visited.append(path)
        r = client.get(r.location)
    return r, visited


def _assert_old_cookie_cannot_reach_dashboard(flask_app, user, token):
    assert (
        MfaBrowser.get_by(token=token) is None
    ), "the trusted-browser row survived the second-factor change"
    attacker = flask_app.test_client()
    _set_cookie(attacker, "mfa", token)
    r, visited = _login_following_gates(attacker, user)
    # the bypass in mfa.py/fido.py answers GET /auth/mfa|/auth/fido with a
    # 302 to the dashboard without calling login_user: reaching /dashboard
    # straight from a gate means the revoked cookie still authenticated.
    gate_idx = next(
        (i for i, p in enumerate(visited) if p in ("/auth/mfa", "/auth/fido")), None
    )
    if gate_idx is not None:
        assert "/dashboard" not in visited[gate_idx + 1 :], (
            f"a trusted-browser cookie minted before the 2FA change still "
            f"bypasses it (visited: {visited})"
        )


def test_mfa_setup_revokes_trusted_browser(flask_app, flask_client):
    """Enabling TOTP revokes trusted browsers minted against the old state."""
    user = create_new_user()
    Session.commit()
    _login(flask_client, user)
    token = _mint_trusted_browser_directly(user)

    _enable_totp(flask_client, user)
    assert user.enable_otp is True

    _assert_old_cookie_cannot_reach_dashboard(flask_app, user, token)
    # sanity: the legitimate user still faces the new factor on a clean client
    legit = flask_app.test_client()
    r = legit.post(
        url_for("auth.login"), data={"email": user.email, "password": "password"}
    )
    assert r.status_code == 302 and "/auth/mfa" in r.location


def test_mfa_cancel_revokes_trusted_browser(flask_app, flask_client):
    """Disabling TOTP revokes trusted browsers, including ones minted under it."""
    user = create_new_user()
    Session.commit()
    _login(flask_client, user)
    secret = _enable_totp(flask_client, user)
    token = _mint_trusted_browser_via_endpoints(flask_client, user, secret)

    # the trusted browser currently works: clean client + password gets in
    working = flask_app.test_client()
    _set_cookie(working, "mfa", token)
    r = working.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )
    assert r.status_code == 200 and b"/auth/logout" in r.data

    enter_sudo_mode(flask_client, user)
    r = flask_client.post(
        url_for("dashboard.mfa_cancel"), data={}, follow_redirects=True
    )
    assert r.status_code == 200
    assert user.enable_otp is False and user.otp_secret is None

    _assert_old_cookie_cannot_reach_dashboard(flask_app, user, token)


def test_fido_setup_revokes_trusted_browser(flask_app, flask_client):
    """Registering a security key revokes trusted browsers minted under TOTP."""
    user = create_new_user()
    Session.commit()
    _login(flask_client, user)
    secret = _enable_totp(flask_client, user)
    token = _mint_trusted_browser_via_endpoints(flask_client, user, secret)

    enter_sudo_mode(flask_client, user)
    # GET fido_setup stores fido_uuid and fido_challenge in the session
    r = flask_client.get(url_for("dashboard.fido_setup"))
    assert r.status_code == 200

    fake_credential = MagicMock()
    fake_credential.credential_id = b"cred-fake"
    fake_credential.public_key = b"pk-fake"
    fake_credential.sign_count = 0
    with patch(
        "app.dashboard.views.fido_setup.webauthn.WebAuthnRegistrationResponse"
    ) as MockResponse:
        MockResponse.return_value.verify.return_value = fake_credential
        r = flask_client.post(
            url_for("dashboard.fido_setup"),
            data={
                "key_name": "My Key",
                "sk_assertion": '{"id": "fake", "type": "public-key"}',
            },
            follow_redirects=True,
        )
    assert r.status_code == 200
    assert user.fido_enabled() is True
    assert Fido.filter_by(user_id=user.id).count() == 1

    _assert_old_cookie_cannot_reach_dashboard(flask_app, user, token)


def test_fido_manage_revokes_trusted_browser(flask_app, flask_client):
    """Deleting the last security key revokes trusted browsers."""
    user = create_new_user()
    Session.commit()
    _login(flask_client, user)
    key = _register_hardware_key(user)
    token = _mint_trusted_browser_directly(user)

    enter_sudo_mode(flask_client, user)
    r = flask_client.post(
        url_for("dashboard.fido_manage"),
        data={"credential_id": key.credential_id},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert user.fido_enabled() is False

    # the row is gone; with no second factor left a password login goes to the
    # dashboard through after_login, not through the trusted-browser gate
    assert (
        MfaBrowser.get_by(token=token) is None
    ), "the trusted-browser row survived the key deletion"
    attacker = flask_app.test_client()
    _set_cookie(attacker, "mfa", token)
    _, visited = _login_following_gates(attacker, user)
    # no gate exists anymore, so /auth/fido must not appear in the chain
    assert "/auth/fido" not in visited
