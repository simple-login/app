"""CSRF enforcement on the custom (non-ModelView) admin views.

The hand-written admin views (email search, custom domain search) act directly
on ``request.form`` and had no CSRF token check at all. These tests run with
``WTF_CSRF_ENABLED`` turned back on - the suite-wide default disables it - and
assert that a POST without a valid token is refused before the handler runs.
"""

import hashlib
import os
import re
from time import time
from typing import Callable, Generator, Optional
from urllib.parse import urlparse

import arrow
import pytest
from flask import url_for
from itsdangerous import TimestampSigner
from itsdangerous.url_safe import URLSafeTimedSerializer
from itsdangerous.encoding import base64_encode, int_to_bytes, want_bytes

from app import config
from app.db import Session
from app.models import (
    AdminAuditLog,
    Alias,
    AuditLogActionEnum,
    CustomDomain,
    Fido,
    ForbiddenMxIp,
    Mailbox,
    PartnerUser,
    User,
)
from app.proton.proton_partner import get_proton_partner
from tests.conftest import app
from tests.utils import create_new_user, random_token


class _csrf_enabled:
    """Context manager restoring the previous ``WTF_CSRF_ENABLED`` on exit.

    The suite disables CSRF globally (tests/conftest.py); these tests need it
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


CSRF_WARNING_MESSAGE = "Invalid request"

# A form submitted more than WTF_CSRF_TIME_LIMIT ago must be refused even while
# the admin grace period (43200 s by default) is still fresh.
EXPIRED_TOKEN_AGE_SECONDS = 3600 + 60


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


@pytest.fixture(autouse=True)
def csrf_admin(flask_client) -> Generator[User, None, None]:
    """An admin signed in over HTTP, with CSRF enforcement switched on.

    Autouse because the suite disables CSRF globally and every test in this
    module needs it back on. The flag is flipped on after signing in - a login
    attempted with validation on does not fail loudly, it re-renders the login
    page, and the test would silently act as an anonymous visitor - so the
    sign-in helper pins the flag off for its own duration.
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


def fresh_csrf_token(flask_client) -> str:
    """A valid token taken from the rendered email-search page.

    Reading the token out of the served HTML - the exact value a browser would
    submit - is what proves the token the UI hands out is the one the server
    accepts. Hand-signing tokens (see the expiry test) bypasses that link.
    The token lives in the action forms, which only render for a search that
    found something, so the page is fetched with a fresh user's email.
    """
    user = create_new_user()
    Session.commit()
    r = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": user.email, "search_type": "email"},
        follow_redirects=True,
    )
    if r.status_code != 200 or "csrf_token" not in r.data.decode(errors="ignore"):
        # A denial (logout, expired grace) redirects away from the page; make
        # sure the caller's own denial is the one under test, not ours.
        raise AssertionError(f"could not load the admin page: {r.status_code}")
    return _extract_csrf_token(r.data.decode())


def expired_csrf_token(flask_client, age_seconds: int) -> str:
    """A token whose signature matches the session but is stamped too far back.

    Flask-WTF stores a random value in the session and sends a timed, signed
    serialization of it, so the pair stays consistent; only the timestamp lies.
    This is the one case that cannot come from a rendered page: no honest
    server hands out an expired token.
    """
    # Seed the session value through Flask-WTF itself, via a page that renders
    # a form; the value is deliberately absent from the session until then.
    seed = flask_client.get(
        url_for("admin.email_search.index"),
        query_string={"query": create_new_user_email(), "search_type": "email"},
    )
    assert seed.status_code == 200
    unsigned = _extract_csrf_token(seed.data.decode()).rsplit(".", 1)[0]
    return _sign_older_than(unsigned, age_seconds)


def create_new_user_email() -> str:
    user = create_new_user()
    Session.commit()
    return user.email


def _sign_older_than(value: str, age_seconds: int) -> str:
    """itsdangerous timestamps a ``sign`` call with the current time only, so
    build the payload exactly like ``TimestampSigner.sign`` and sign that."""
    secret_key = app.config.get("WTF_CSRF_SECRET_KEY") or app.secret_key
    assert secret_key is not None, "a secret key is required to sign CSRF tokens"
    signer = TimestampSigner(secret_key, salt="wtf-csrf-token")
    payload = (
        want_bytes(value)
        + signer.sep
        + base64_encode(int_to_bytes(int(time()) - age_seconds))
    )
    return (payload + signer.sep + signer.get_signature(payload)).decode()


def flash_messages(client) -> str:
    """Flash messages queued in the session of ``client``.

    Read straight from the session because Flask pops them on the next render,
    which would make the assertion depend on whether the page template happens
    to display them.
    """
    with client.session_transaction() as sess:
        return "; ".join(str(message[1]) for message in sess.get("_flashes", []))


def clear_flash_messages(client) -> None:
    """Drop queued flashes so the next assertion cannot match an older request's."""
    with client.session_transaction() as sess:
        sess.pop("_flashes", None)


def assert_rejected_by_csrf_guard(flask_client, url: str, data: dict) -> None:
    """Refused by the CSRF guard, not by a business rule: redirect to the view
    index carrying the "Invalid request" warning."""
    r = flask_client.post(url, data=data)
    assert r.status_code == 302, r.data[:2000]
    assert url_for("admin.email_search.index") in r.headers["Location"]
    assert CSRF_WARNING_MESSAGE in flash_messages(flask_client), flash_messages(
        flask_client
    )


def assert_redirected_before_csrf(flask_client, url: str, data: dict, destination: str):
    """Access control runs before the CSRF guard, so an unauthorized client
    gets its usual denial redirect and never the CSRF warning."""
    r = flask_client.post(url, data=data)
    assert r.status_code == 302, r.data[:2000]
    assert destination in r.headers["Location"], r.headers["Location"]
    assert CSRF_WARNING_MESSAGE not in flash_messages(flask_client)


# ---------------------------------------------------------------------------
# Fixtures for the targets of the admin actions
# ---------------------------------------------------------------------------


def _user_with_totp() -> User:
    user = create_new_user()
    user.enable_otp = True
    user.otp_secret = random_token(16)
    Session.commit()
    return user


def _disabled_user() -> User:
    user = create_new_user()
    user.disabled = True
    Session.commit()
    return user


def _new_alias() -> Alias:
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=f"csrfalias_{random_token(8)}@sl.lan",
        mailbox_id=user.default_mailbox_id,
        flush=True,
    )
    Session.commit()
    return alias


def _new_mailbox(email_prefix: str = "csrfmailbox") -> Mailbox:
    user = create_new_user()
    mailbox = Mailbox.create(
        user_id=user.id,
        email=f"{email_prefix}_{random_token(8)}@example.com",
        verified=True,
        flush=True,
    )
    Session.commit()
    return mailbox


def _partner_linked_user() -> PartnerUser:
    user = create_new_user()
    partner_user = PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        external_user_id=random_token(10),
        partner_email=f"proton_{random_token(8)}@proton.ch",
        flush=True,
    )
    Session.commit()
    return partner_user


def _new_custom_domain() -> CustomDomain:
    user = create_new_user()
    domain = CustomDomain.create(
        user_id=user.id,
        domain=f"csrf-domain-{random_token(8)}.com",
        ownership_verified=True,
        verified=True,
        flush=True,
    )
    Session.commit()
    return domain


# ---------------------------------------------------------------------------
# Payload factories: (url, valid form data, target-state-changed predicate)
# ---------------------------------------------------------------------------


def _payload_disable_2fa() -> tuple:
    user = _user_with_totp()
    return (
        url_for("admin.email_search.disable_2fa"),
        {"user_id": user.id},
        lambda: User.get(user.id).enable_otp is False,
    )


def _payload_unmark_abuser() -> tuple:
    user = _disabled_user()
    return (
        url_for("admin.email_search.unmark_abuser"),
        {"user_id": user.id, "note": "not an abuser anymore"},
        lambda: User.get(user.id).disabled is False,
    )


def _payload_mark_abuser() -> tuple:
    user = create_new_user()
    Session.commit()
    return (
        url_for("admin.email_search.mark_abuser"),
        {"user_id": user.id, "note": "sending spam"},
        lambda: bool(User.get(user.id).disabled),
    )


def _payload_update_subdomain_quota() -> tuple:
    user = create_new_user()
    Session.commit()
    return (
        url_for("admin.email_search.update_subdomain_quota"),
        {"user_id": user.id, "subdomain_quota": 7},
        lambda: User.get(user.id)._subdomain_quota == 7,
    )


def _payload_update_directory_quota() -> tuple:
    user = create_new_user()
    Session.commit()
    return (
        url_for("admin.email_search.update_directory_quota"),
        {"user_id": user.id, "directory_quota": 7},
        lambda: User.get(user.id)._directory_quota == 7,
    )


def _payload_stop_user_deletion() -> tuple:
    user = create_new_user()
    user.delete_on = arrow.now().shift(days=7)
    Session.commit()
    return (
        url_for("admin.email_search.stop_user_deletion"),
        {"user_id": user.id},
        lambda: User.get(user.id).delete_on is None,
    )


def _payload_toggle_alias_status() -> tuple:
    alias = _new_alias()
    assert alias.enabled
    return (
        url_for("admin.email_search.toggle_alias_status"),
        {"alias_id": alias.id, "note": "blocked by admin"},
        lambda: Alias.get(alias.id).enabled is False,
    )


def _payload_delete_alias() -> tuple:
    alias = _new_alias()
    return (
        url_for("admin.email_search.delete_alias"),
        {"alias_id": alias.id, "confirm_email": alias.email, "note": "abuse"},
        lambda: Alias.get(alias.id) is None,
    )


def _payload_set_default_mailbox() -> tuple:
    mailbox = _new_mailbox()
    user = mailbox.user
    other = Mailbox.create(
        user_id=user.id,
        email=f"csrfmailbox2_{random_token(8)}@example.com",
        verified=True,
        flush=True,
    )
    user.default_mailbox_id = mailbox.id
    Session.commit()
    return (
        url_for("admin.email_search.set_default_mailbox"),
        {"mailbox_id": other.id},
        # The handler writes its audit row with an unconverted enum and raises,
        # so "the default did not move" is the observable refusal here.
        lambda: User.get(user.id).default_mailbox_id != mailbox.id,
    )


def _payload_admin_disable_mailbox() -> tuple:
    mailbox = _new_mailbox()
    return (
        url_for("admin.email_search.admin_disable_mailbox"),
        {"mailbox_id": mailbox.id, "note": "used for spam"},
        lambda: Mailbox.get(mailbox.id).is_admin_disabled(),
    )


def _payload_admin_reenable_mailbox() -> tuple:
    mailbox = _new_mailbox()
    mailbox.flags = mailbox.flags | Mailbox.FLAG_ADMIN_DISABLED
    Session.commit()
    return (
        url_for("admin.email_search.admin_reenable_mailbox"),
        {"mailbox_id": mailbox.id, "note": "appealed"},
        lambda: not Mailbox.get(mailbox.id).is_admin_disabled(),
    )


def _payload_send_mailbox_disable_warning(sent_mail: list) -> tuple:
    mailbox = _new_mailbox()
    return (
        url_for("admin.email_search.send_mailbox_disable_warning"),
        {"mailbox_id": mailbox.id, "note": "spam detected"},
        lambda: mailbox.email in sent_mail,
    )


def _payload_delete_user() -> tuple:
    user = create_new_user()
    Session.commit()
    user_id, user_email = user.id, user.email
    return (
        url_for("admin.email_search.delete_user"),
        {"user_id": user_id, "confirm_email": user_email},
        lambda: User.get(user_id) is None,
    )


def _payload_delete_partner_link() -> tuple:
    partner_user = _partner_linked_user()
    return (
        url_for("admin.email_search.delete_partner_link"),
        {
            "user_id": partner_user.user_id,
            "confirm_email": partner_user.partner_email,
        },
        lambda: PartnerUser.get_by(user_id=partner_user.user_id) is None,
    )


def _payload_delete_custom_domain() -> tuple:
    domain = _new_custom_domain()
    return (
        url_for("admin.custom_domain_search.delete_custom_domain"),
        {"domain_id": domain.id, "confirm_domain": domain.domain},
        # The handler only schedules deletion; the row stays until the cron
        # runs, so the audit log is the observable trace of the action.
        lambda: Session.query(AdminAuditLog)
        .filter_by(model="CustomDomain", model_id=domain.id)
        .first()
        is not None,
    )


EMAIL_SEARCH_PAYLOADS: dict[str, Callable[..., tuple]] = {
    "delete_partner_link": _payload_delete_partner_link,
    "stop_user_deletion": _payload_stop_user_deletion,
    "update_subdomain_quota": _payload_update_subdomain_quota,
    "update_directory_quota": _payload_update_directory_quota,
    "mark_abuser": _payload_mark_abuser,
    "unmark_abuser": _payload_unmark_abuser,
    "disable_2fa": _payload_disable_2fa,
    "delete_user": _payload_delete_user,
    "toggle_alias_status": _payload_toggle_alias_status,
    "delete_alias": _payload_delete_alias,
    "send_mailbox_disable_warning": _payload_send_mailbox_disable_warning,
    "admin_disable_mailbox": _payload_admin_disable_mailbox,
    "admin_reenable_mailbox": _payload_admin_reenable_mailbox,
    "set_default_mailbox": _payload_set_default_mailbox,
}


@pytest.fixture
def sent_mail(monkeypatch) -> list:
    """Record recipients instead of handing mail to the test SMTP sink.

    Needed because a forged POST to ``send_mailbox_disable_warning`` leaves no
    database trace, so "the database did not change" proves nothing there.
    """
    from app import email_utils

    sent: list[str] = []

    def fake_send_email(to_addr, *args, **kwargs):
        recipients = to_addr if isinstance(to_addr, (list, tuple)) else [to_addr]
        sent.extend(recipients)

    monkeypatch.setattr(email_utils, "send_email", fake_send_email)
    monkeypatch.setattr("app.mailbox_utils.send_email", fake_send_email)
    return sent


def _run_payload(payload_factory, sent_mail):
    return (
        payload_factory(sent_mail)
        if payload_factory is _payload_send_mailbox_disable_warning
        else payload_factory()
    )


@pytest.mark.parametrize(
    "payload_factory",
    list(EMAIL_SEARCH_PAYLOADS.values()),
    ids=list(EMAIL_SEARCH_PAYLOADS.keys()),
)
def test_post_without_csrf_token_is_rejected(
    csrf_admin, flask_client, payload_factory, sent_mail
):
    url, data, target_state_changed = _run_payload(payload_factory, sent_mail)

    assert_rejected_by_csrf_guard(flask_client, url, data)

    assert sent_mail == []
    Session.expire_all()
    assert not target_state_changed(), f"{url} changed state without a CSRF token"


@pytest.mark.parametrize(
    "payload_factory",
    list(EMAIL_SEARCH_PAYLOADS.values()),
    ids=list(EMAIL_SEARCH_PAYLOADS.keys()),
)
def test_post_with_invalid_csrf_token_is_rejected(
    csrf_admin, flask_client, payload_factory, sent_mail
):
    url, data, target_state_changed = _run_payload(payload_factory, sent_mail)

    for bad_token in ("", "not-a-real-token"):
        clear_flash_messages(flask_client)
        assert_rejected_by_csrf_guard(
            flask_client, url, {**data, "csrf_token": bad_token}
        )

    assert sent_mail == []
    Session.expire_all()
    assert not target_state_changed(), f"{url} changed state with a bad CSRF token"


def test_post_with_foreign_session_csrf_token_is_rejected(csrf_admin, flask_client):
    url, data, target_state_changed = _payload_disable_2fa()
    foreign_token = _token_of_a_different_session()

    assert_rejected_by_csrf_guard(
        flask_client, url, {**data, "csrf_token": foreign_token}
    )

    Session.expire_all()
    assert not target_state_changed()


def test_post_with_expired_csrf_token_is_rejected_and_reload_recovers(
    csrf_admin, flask_client
):
    url, data, target_state_changed = _payload_disable_2fa()
    # The disable-2fa form renders on this user's search page; reuse that page
    # for the reload-recovery step so the retry token comes from rendered HTML.
    target_email = User.get(int(data["user_id"])).email
    page_query = {"query": target_email, "search_type": "email"}
    expired_token = expired_csrf_token(flask_client, EXPIRED_TOKEN_AGE_SECONDS)

    assert_rejected_by_csrf_guard(
        flask_client, url, {**data, "csrf_token": expired_token}
    )
    Session.expire_all()
    assert not target_state_changed()

    # The admin reloads the page - which hands out a fresh token - and retries.
    # The disable-2fa form is rendered only on the search page that finds the
    # target user, so reload exactly that page and take its token.
    page = flask_client.get(
        url_for("admin.email_search.index"), query_string=page_query
    )
    assert page.status_code == 200
    page_html = page.data.decode()
    # The form tag spans several lines, so search the whole page for a POST
    # form aimed at the target endpoint and take the first token after it.
    # Jinja escapes the url_for output inside the action attribute (& -> &amp;),
    # so match on the endpoint name instead of the exact URL.
    form_match = re.search(
        r'<form[^>]{0,400}?action="[^"]*disable_2fa"', page_html, re.DOTALL
    )
    assert form_match is not None, "the reload did not render the disable-2fa form"
    token_input = _CSRF_INPUT_TAG.search(page_html, form_match.start())
    assert token_input is not None, "the rendered form carries no CSRF token"
    r = flask_client.post(
        url,
        data={
            **data,
            "csrf_token": _extract_csrf_token(page_html[form_match.start() :]),
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert CSRF_WARNING_MESSAGE not in flash_messages(flask_client)
    Session.expire_all()
    assert target_state_changed()


@pytest.mark.parametrize(
    "payload_factory",
    [EMAIL_SEARCH_PAYLOADS["mark_abuser"], EMAIL_SEARCH_PAYLOADS["disable_2fa"]],
    ids=["mark_abuser", "disable_2fa"],
)
def test_post_with_valid_csrf_token_succeeds(csrf_admin, flask_client, payload_factory):
    url, data, target_state_changed = payload_factory()

    r = flask_client.post(
        url,
        data={**data, "csrf_token": fresh_csrf_token(flask_client)},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert CSRF_WARNING_MESSAGE not in flash_messages(flask_client)
    Session.expire_all()
    assert target_state_changed()


def test_index_get_still_works_with_csrf_enabled(csrf_admin, flask_client):
    r = flask_client.get(url_for("admin.email_search.index"))
    assert r.status_code == 200
    assert b"Email Search" in r.data


def test_index_post_without_csrf_token_is_rejected(csrf_admin, flask_client):
    """The email-search index itself accepts POST and is covered by the same
    guard as the action endpoints."""
    url = url_for("admin.email_search.index")

    r = flask_client.post(url, data={"query": "someone@example.com"})

    assert r.status_code == 302
    assert url_for("admin.email_search.index") in r.headers["Location"]
    assert CSRF_WARNING_MESSAGE in flash_messages(flask_client)


def test_anonymous_post_is_denied_before_csrf(csrf_admin, flask_client):
    """Access control runs first, so an anonymous visitor gets the login
    redirect - and no hint that a valid token would have been accepted."""
    url, data, target_state_changed = _payload_disable_2fa()
    token = fresh_csrf_token(flask_client)
    flask_client.get(url_for("auth.logout"))

    assert_redirected_before_csrf(
        flask_client,
        url,
        {**data, "csrf_token": token},
        _login_url_prefix(),
    )

    Session.expire_all()
    assert not target_state_changed()


def test_non_admin_post_is_denied_before_csrf(csrf_admin, flask_client):
    """A signed-in non-admin gets the access-control denial, not the CSRF warning.

    Signed in as a plain user after the autouse admin fixture, which replaces
    the session.
    """
    plain_user = create_new_user()
    Session.commit()
    _login(flask_client, plain_user)

    url, data, target_state_changed = _payload_disable_2fa()

    assert_redirected_before_csrf(
        flask_client,
        url,
        {**data, "csrf_token": fresh_csrf_token(flask_client)},
        _login_url_prefix(),
    )

    Session.expire_all()
    assert not target_state_changed()


def _login_url_prefix() -> str:
    """Login URL without its query string.

    ``_redirect_if_user_is_not_allowed`` puts the full admin URL in ``next``,
    and ``sanitize_next_url`` keeps only the path for a host outside
    ALLOWED_REDIRECT_DOMAINS, so matching the whole URL would be brittle.
    """
    return urlparse(url_for("auth.login")).path


def test_admin_past_grace_period_is_denied_before_csrf(
    csrf_admin, flask_client, monkeypatch
):
    """A valid token must not keep an expired admin session inside the view."""
    # The grace period is only consulted once a key ceremony is required, so
    # switch that on and stamp admin_time before the window opened.
    monkeypatch.setattr("app.admin.base.config.ADMIN_FIDO_REQUIRED", "any")
    _give_admin_a_fido_key(csrf_admin)
    token = fresh_csrf_token(flask_client)
    with flask_client.session_transaction() as sess:
        sess["admin_time"] = int(time()) - config.ADMIN_GRACE_PERIOD - 60
    del sess  # noqa: B018 - readability; the with-block above already committed

    url, data, target_state_changed = _payload_disable_2fa()

    assert_redirected_before_csrf(
        flask_client,
        url,
        {**data, "csrf_token": token},
        url_for("dashboard.enter_admin"),
    )

    Session.expire_all()
    assert not target_state_changed()


def test_admin_without_hardware_key_auth_is_denied_before_csrf(
    csrf_admin, flask_client, monkeypatch
):
    """Grace-period entry obtained without a hardware key still expires."""
    monkeypatch.setattr("app.admin.base.config.ADMIN_FIDO_REQUIRED", "hardware")
    _give_admin_a_fido_key(csrf_admin)
    token = fresh_csrf_token(flask_client)
    with flask_client.session_transaction() as sess:
        sess.pop("admin_hardware_auth", None)

    url, data, target_state_changed = _payload_disable_2fa()

    assert_redirected_before_csrf(
        flask_client,
        url,
        {**data, "csrf_token": token},
        url_for("dashboard.enter_admin"),
    )

    Session.expire_all()
    assert not target_state_changed()


def _give_admin_a_fido_key(admin_user: User) -> None:
    """Register a key so the denial lands on enter_admin.

    Without one, `_redirect_if_user_is_not_allowed` sends the admin to account
    settings instead, which would test a different branch.
    """
    admin_user.fido_uuid = random_token(16)
    Session.commit()
    Fido.create(
        credential_id=random_token(32),
        uuid=admin_user.fido_uuid,
        public_key=random_token(64),
        sign_count=0,
        name="Admin Key",
        user_id=admin_user.id,
        flush=True,
    )
    Session.commit()


def _token_of_a_different_session() -> str:
    """A token signed with the app secret but bound to no session the server
    can see, so it can only fail the session comparison."""
    secret_key = app.config.get("WTF_CSRF_SECRET_KEY") or app.secret_key
    assert secret_key is not None, "a secret key is required to sign CSRF tokens"
    foreign = hashlib.sha1(os.urandom(64)).hexdigest()
    return str(URLSafeTimedSerializer(secret_key, salt="wtf-csrf-token").dumps(foreign))


# ---------------------------------------------------------------------------
# Templates: every rendered POST form must carry a token
# ---------------------------------------------------------------------------

_FORM_TAG = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_CSRF_INPUT_TAG = re.compile(r"""<input[^>]*name=["']csrf_token["'][^>]*>""")
_ATTR_VALUE = re.compile(r"""value=["']([^"']*)["']""")


def _extract_csrf_token(html: str) -> str:
    """The first CSRF token rendered in ``html`` - the one the UI would submit."""
    tag = _CSRF_INPUT_TAG.search(html)
    assert tag is not None, "no csrf_token input in the page"
    match = _ATTR_VALUE.search(tag.group(0))
    assert match is not None and match.group(1), "csrf_token input carries no value"
    return match.group(1)


def _post_forms(html: str) -> list[tuple[str, str]]:
    """Return (form tag, body) for every POST <form> element in ``html``."""
    tags = list(_FORM_TAG.finditer(html))
    forms = []
    for index, match in enumerate(tags):
        end = tags[index + 1].start() if index + 1 < len(tags) else len(html)
        if re.search(r'method=["\']?post', match.group(0), re.IGNORECASE):
            forms.append((match.group(0), html[match.end() : end]))
    return forms


def _forms_missing_csrf_token(html: str) -> list[str]:
    return [
        tag
        for tag, body in _post_forms(html)
        if not re.search(r"""name=["']csrf_token["']""", body)
    ]


def _render_email_search_with_every_action(flask_client) -> str:
    """Render the email-search page with data that makes every action form show.

    Runs under the ``csrf_admin`` fixture: the fixtures below commit, which
    would wipe a not-yet-committed admin, so the signed-in admin is never
    recreated here.
    """
    user = create_new_user()
    user.enable_otp = True
    user.otp_secret = random_token(16)
    user.fido_uuid = random_token(16)
    user.delete_on = arrow.now().shift(days=7)
    Session.flush()
    Fido.create(
        credential_id=random_token(32),
        uuid=user.fido_uuid,
        public_key=random_token(64),
        sign_count=0,
        name="Test Key",
        user_id=user.id,
        flush=True,
    )
    PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        external_user_id=random_token(10),
        partner_email=f"proton_{random_token(8)}@proton.ch",
        flush=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email=f"csrfpage_{random_token(8)}@sl.lan",
        mailbox_id=user.default_mailbox_id,
        flush=True,
    )
    Mailbox.create(
        user_id=user.id,
        email=f"csrfpage_{random_token(8)}@example.com",
        verified=True,
        flush=True,
    )
    admin_disabled_mailbox = Mailbox.create(
        user_id=user.id,
        email=f"csrfpagedisabled_{random_token(8)}@example.com",
        verified=True,
        flush=True,
    )
    admin_disabled_mailbox.flags = (
        admin_disabled_mailbox.flags | Mailbox.FLAG_ADMIN_DISABLED
    )
    CustomDomain.create(
        user_id=user.id,
        domain=f"csrf-page-{random_token(8)}.com",
        ownership_verified=True,
        verified=True,
        flush=True,
    )
    Session.commit()

    html = ""
    for search_type, query in (("email", user.email), ("alias", alias.email)):
        r = flask_client.get(
            url_for("admin.email_search.index"),
            query_string={"query": query, "search_type": search_type},
        )
        assert r.status_code == 200
        html += r.data.decode()
    # Sanity check: the fixtures really made every action form appear.
    # Inside a request, url_for emits the relative path the template uses.
    with flask_client.application.test_request_context():
        for endpoint in (
            "disable_2fa",
            "stop_user_deletion",
            "delete_user",
            "mark_abuser",
            "unmark_abuser",
            "delete_partner_link",
            "update_subdomain_quota",
            "update_directory_quota",
            "toggle_alias_status",
            "delete_alias",
            "set_default_mailbox",
            "admin_disable_mailbox",
            "admin_reenable_mailbox",
            "send_mailbox_disable_warning",
        ):
            assert url_for(f"admin.email_search.{endpoint}") in html, endpoint
    return html


def test_email_search_page_renders_csrf_token_in_every_post_form(
    csrf_admin, flask_client
):
    html = _render_email_search_with_every_action(flask_client)

    assert len(_post_forms(html)) >= 14
    missing = _forms_missing_csrf_token(html)
    assert missing == [], f"POST forms without a csrf_token field: {missing}"


def test_custom_domain_search_page_renders_csrf_token_in_every_post_form(
    csrf_admin, flask_client
):
    domain = _new_custom_domain()

    r = flask_client.get(
        url_for("admin.custom_domain_search.index"),
        query_string={"query": domain.domain},
    )
    assert r.status_code == 200
    html = r.data.decode()
    with flask_client.application.test_request_context():
        assert url_for("admin.custom_domain_search.delete_custom_domain") in html

    missing = _forms_missing_csrf_token(html)
    assert missing == [], f"POST forms without a csrf_token field: {missing}"


def test_custom_domain_delete_without_csrf_token_is_rejected(csrf_admin, flask_client):
    url, data, target_state_changed = _payload_delete_custom_domain()

    r = flask_client.post(url, data=data)

    assert r.status_code == 302
    assert url_for("admin.custom_domain_search.index") in r.headers["Location"]
    assert CSRF_WARNING_MESSAGE in flash_messages(flask_client)
    Session.expire_all()
    assert not target_state_changed()


def test_custom_domain_delete_with_csrf_token_succeeds(csrf_admin, flask_client):
    url, data, target_state_changed = _payload_delete_custom_domain()

    r = flask_client.post(
        url,
        data={**data, "csrf_token": fresh_csrf_token(flask_client)},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert CSRF_WARNING_MESSAGE not in flash_messages(flask_client)
    Session.expire_all()
    assert target_state_changed()


# ---------------------------------------------------------------------------
# ModelView regression: the SecureForm token flow must keep working
# ---------------------------------------------------------------------------


def test_modelview_secureform_still_validates_with_csrf_enabled(
    csrf_admin, flask_client
):
    """Binding correction 5: ``SLModelView`` views use flask-admin's
    ``SecureForm``, whose token is a plain session hash - a different scheme
    from the Flask-WTF token checked by ``CSRFProtectedAdminView``. The two
    guards must not be mixed: a create form rendered by a ModelView and
    submitted with its own page token still succeeds with CSRF enforcement on,
    and the missing guard there is flask-admin's own, not the new hook."""
    ip = "203.0.113.23"
    create_url = url_for("forbiddenmxip.create_view")

    r = flask_client.get(create_url)
    assert r.status_code == 200
    token = _extract_csrf_token(r.data.decode())

    r = flask_client.post(
        create_url,
        data={"ip": ip, "comment": "csrf regression", "csrf_token": token},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert CSRF_WARNING_MESSAGE not in flash_messages(flask_client)
    # The row exists and the create audit row was written with .value: an
    # unvalidated form never reaches on_model_change, and an audit write that
    # crashes there rolls the create back, so together they prove the
    # SecureForm token was accepted end to end.
    assert Session.query(ForbiddenMxIp).filter_by(ip=ip).first() is not None
    assert (
        Session.query(AdminAuditLog)
        .filter_by(model="ForbiddenMxIp", action=AuditLogActionEnum.create_object.value)
        .first()
        is not None
    )


def test_modelview_secureform_without_token_is_refused_by_flask_admin(
    csrf_admin, flask_client
):
    """Same view, no token: flask-admin's own SecureForm validation refuses the
    create, so the ModelView was never unprotected by the absence of the new
    hook."""
    ip = "203.0.113.24"
    create_url = url_for("forbiddenmxip.create_view")

    r = flask_client.get(create_url)
    assert r.status_code == 200

    r = flask_client.post(
        create_url, data={"ip": ip, "comment": "no token"}, follow_redirects=True
    )

    assert r.status_code == 200
    # flask-admin re-renders the create form with the field value kept and the
    # model untouched when SecureForm rejects the missing token.
    assert b"no token" in r.data
    assert Session.query(ForbiddenMxIp).filter_by(ip=ip).first() is None
