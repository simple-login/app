from typing import Optional
from urllib.parse import parse_qs

from urllib3.util import parse_url

from flask import url_for

from app.auth.views.proton import (
    Action,
    SESSION_ACTION_KEY,
    SESSION_LINK_USER_ID_KEY,
    SESSION_STATE_KEY,
)
from app.config import URL, PROTON_CLIENT_ID
from app.models import ApiKey, PartnerUser
from app import config
from app.account_linking import SLPlan, SLPlanType
from app.proton.proton_client import ProtonUser
from app.proton.proton_partner import get_proton_partner
from tests.utils import (
    create_new_user,
    create_partner_linked_user,
    enter_sudo_mode,
    exit_sudo_mode,
    login,
    random_token,
)


def test_login_with_proton(flask_client):
    r = flask_client.get(
        url_for("auth.proton_login"),
        follow_redirects=False,
    )
    location = r.headers.get("Location")
    assert location is not None

    parsed = parse_url(location)
    query = parse_qs(parsed.query)

    expected_redirect_url = f"{URL}/auth/proton/callback"

    assert "code" == query["response_type"][0]
    assert PROTON_CLIENT_ID == query["client_id"][0]
    assert expected_redirect_url == query["redirect_uri"][0]


def _proton_user() -> ProtonUser:
    return ProtonUser(
        email=f"proton_{random_token(6)}@proton.me",
        plan=SLPlan(type=SLPlanType.Free, expiration=None),
        name="Proton User",
        id=random_token(10),
    )


def _mock_proton_callback(monkeypatch, handler_get_user_return=None):
    """Make the Proton callback runnable offline: fake token fetch + fake Proton user."""
    monkeypatch.setattr(
        "requests_oauthlib.OAuth2Session.fetch_token",
        lambda self, *args, **kwargs: {"access_token": "pt-session-token"},
    )
    monkeypatch.setattr(
        "app.proton.proton_client.HttpProtonClient.get_user",
        lambda self: handler_get_user_return,
    )


def _seed_link_callback_session(flask_client, action_value, state="state-123"):
    with flask_client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = state
        sess[SESSION_ACTION_KEY] = action_value


def test_link_start_without_sudo_redirects_to_enter_sudo(flask_client):
    login(flask_client)
    # password login grants sudo; simulate a session whose sudo has expired
    exit_sudo_mode(flask_client)

    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    location = parse_url(r.headers["Location"])
    assert location.path == "/dashboard/enter_sudo"
    # next must keep action=link so the user resumes the link flow after sudo
    next_query = parse_qs(parse_url(parse_qs(location.query)["next"][0]).query)
    assert next_query["action"] == ["link"]
    # The link must not have started: no OAuth state stored
    with flask_client.session_transaction() as sess:
        assert SESSION_STATE_KEY not in sess
        assert SESSION_ACTION_KEY not in sess


def test_link_start_sudo_roundtrip_keeps_link_action(flask_client):
    """Full enter_sudo round-trip: after the password check the user lands back
    on the Proton link start, not on the login flow."""
    user = login(flask_client)
    # password login grants sudo; simulate a session whose sudo has expired
    exit_sudo_mode(flask_client)

    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = parse_url(r.headers["Location"])
    assert location.path == "/dashboard/enter_sudo"
    next_url = parse_qs(location.query)["next"][0]

    # keep the full next URL (path + query) as the real redirector does
    r = flask_client.post(
        f"/dashboard/enter_sudo?next={next_url}",
        data={"password": "password"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    # enter_sudo redirects to the proton link start...
    assert parse_url(r.headers["Location"]).path == "/auth/proton/login"

    r = flask_client.get(r.headers["Location"], follow_redirects=False)
    assert r.status_code == 302
    # ...which now starts the LINK flow, not the login flow
    assert "/oauth/authorize" in r.headers["Location"]
    with flask_client.session_transaction() as sess:
        assert sess[SESSION_ACTION_KEY] == Action.Link.value
        assert sess[SESSION_LINK_USER_ID_KEY] == user.id


def test_link_start_with_sudo_redirects_to_proton(flask_client):
    user = login(flask_client)
    enter_sudo_mode(flask_client, user)

    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert "/oauth/authorize" in r.headers["Location"]
    with flask_client.session_transaction() as sess:
        assert sess[SESSION_ACTION_KEY] == Action.Link.value


def test_link_callback_does_not_grant_sudo_mode(flask_client, monkeypatch):
    user = login(flask_client)
    enter_sudo_mode(flask_client, user)
    # start the link flow in sudo mode...
    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    # ...then the sudo expires while the user authenticates on Proton
    exit_sudo_mode(flask_client)
    _mock_proton_callback(monkeypatch, _proton_user())

    r = flask_client.get(
        url_for("auth.proton_callback", code="code-123"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert r.headers["Location"] == url_for("dashboard.setting")
    # The Proton identity is now linked to the user...
    assert (
        PartnerUser.get_by(user_id=user.id, partner_id=get_proton_partner().id)
        is not None
    )
    # ...but the callback must not re-login the user nor grant sudo mode.
    # The session was already authenticated (login + sudo to start the flow),
    # so assert on the sudo keys and that no fresh login happened.
    from app.session import SUDO_TIME_KEY, SUDO_USER_ID_KEY

    with flask_client.session_transaction() as sess:
        assert SUDO_TIME_KEY not in sess
        assert SUDO_USER_ID_KEY not in sess


def test_link_callback_with_apikey_mode_does_not_create_api_key(
    flask_client, monkeypatch
):
    user = login(flask_client)
    enter_sudo_mode(flask_client, user)
    with flask_client.session_transaction() as sess:
        # leftover from an earlier apikey-mode flow; must be ignored by Link
        sess["oauth_mode"] = "apikey"
    _seed_link_callback_session(flask_client, Action.Link.value)
    with flask_client.session_transaction() as sess:
        # bound to this user so the callback really reaches the link branch
        sess[SESSION_LINK_USER_ID_KEY] = user.id
    _mock_proton_callback(monkeypatch, _proton_user())

    assert ApiKey.filter_by(user_id=user.id).count() == 0

    r = flask_client.get(
        url_for("auth.proton_callback", code="code-123"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    # the link itself ran, so the apikey branch was reached and skipped
    assert (
        PartnerUser.get_by(user_id=user.id, partner_id=get_proton_partner().id)
        is not None
    )
    assert not r.headers["Location"].startswith("auth.simplelogin:")
    assert ApiKey.filter_by(user_id=user.id).count() == 0


def test_link_start_clears_stale_apikey_mode(flask_client):
    user = login(flask_client)
    enter_sudo_mode(flask_client, user)
    with flask_client.session_transaction() as sess:
        # leftover from an earlier apikey-mode login flow
        sess["oauth_mode"] = "apikey"

    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    with flask_client.session_transaction() as sess:
        assert sess["oauth_mode"] == "session"


def test_link_start_without_sudo_ignores_apikey_mode(flask_client):
    login(flask_client)
    exit_sudo_mode(flask_client)

    r = flask_client.get(
        url_for("auth.proton_login", action="link", mode="apikey"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert parse_url(r.headers["Location"]).path == "/dashboard/enter_sudo"


def test_link_callback_without_stored_user_id_does_not_link(flask_client, monkeypatch):
    user = login(flask_client)
    _seed_link_callback_session(flask_client, Action.Link.value)
    with flask_client.session_transaction() as sess:
        # session forged/stale: action says Link but no bound user id
        sess.pop(SESSION_LINK_USER_ID_KEY, None)
    _mock_proton_callback(monkeypatch, _proton_user())

    r = flask_client.get(
        url_for("auth.proton_callback", code="code-123"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert (
        PartnerUser.get_by(user_id=user.id, partner_id=get_proton_partner().id) is None
    )


def test_link_callback_with_different_bound_user_does_not_link(
    flask_client, monkeypatch
):
    user = login(flask_client)
    other_user = create_new_user()
    _seed_link_callback_session(flask_client, Action.Link.value)
    with flask_client.session_transaction() as sess:
        sess[SESSION_LINK_USER_ID_KEY] = other_user.id
    _mock_proton_callback(monkeypatch, _proton_user())

    r = flask_client.get(
        url_for("auth.proton_callback", code="code-123"),
        follow_redirects=False,
    )

    assert r.status_code == 302
    assert (
        PartnerUser.get_by(user_id=user.id, partner_id=get_proton_partner().id) is None
    )


def _proton_user_for(external_user_id: str, email: Optional[str] = None) -> ProtonUser:
    return ProtonUser(
        email=email or f"proton_{random_token(6)}@proton.me",
        plan=SLPlan(type=SLPlanType.Free, expiration=None),
        name="Proton User",
        id=external_user_id,
    )


def test_non_sudo_session_cannot_trigger_switch_already_linked_user(
    flask_client, monkeypatch
):
    """switch_already_linked_user (account_linking.py) moves a Proton identity
    already linked to another SL user whenever
    PROTON_PREVENT_CHANGE_LINKED_ACCOUNT is unset. Reachability invariant: it
    can only run from a link start verified in sudo mode and bound to the same
    user that consumes the callback."""
    # victim: SL user currently linked to the Proton identity
    victim_user, victim_partner_user = create_partner_linked_user()
    # attacker: authenticated SL user, non-sudo session
    attacker_user = login(flask_client)
    exit_sudo_mode(flask_client)

    # step 1: without sudo the link cannot even start
    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert parse_url(r.headers["Location"]).path == "/dashboard/enter_sudo"
    with flask_client.session_transaction() as sess:
        assert SESSION_ACTION_KEY not in sess
        assert SESSION_LINK_USER_ID_KEY not in sess

    # step 2: a stolen/expired session (cookie replayed after the user logged
    # out) cannot consume a link callback even with a stale binding present
    with flask_client.session_transaction() as sess:
        sess[SESSION_STATE_KEY] = "forged-state"
        sess[SESSION_ACTION_KEY] = Action.Link.value
        sess[SESSION_LINK_USER_ID_KEY] = attacker_user.id
    flask_client.get(url_for("auth.logout"))
    _mock_proton_callback(
        monkeypatch, _proton_user_for(victim_partner_user.external_user_id)
    )

    r = flask_client.get(
        url_for("auth.proton_callback", code="code-123"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    # the victim keeps its Proton link
    assert (
        PartnerUser.get_by(
            partner_id=get_proton_partner().id,
            external_user_id=victim_partner_user.external_user_id,
        ).user_id
        == victim_user.id
    )


def test_sudo_verified_link_start_can_trigger_switch_already_linked_user(
    flask_client, monkeypatch
):
    """Control: with a properly sudo-verified link start the switch still works
    (by design, when PROTON_PREVENT_CHANGE_LINKED_ACCOUNT is unset)."""
    assert not config.PROTON_PREVENT_CHANGE_LINKED_ACCOUNT
    victim_user, victim_partner_user = create_partner_linked_user()
    attacker_user = login(flask_client)
    enter_sudo_mode(flask_client, attacker_user)

    r = flask_client.get(
        url_for("auth.proton_login", action="link"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    _mock_proton_callback(
        monkeypatch, _proton_user_for(victim_partner_user.external_user_id)
    )

    r = flask_client.get(
        url_for("auth.proton_callback", code="code-123"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    # the identity moved to the sudo-authenticated attacker
    assert (
        PartnerUser.get_by(
            partner_id=get_proton_partner().id,
            external_user_id=victim_partner_user.external_user_id,
        ).user_id
        == attacker_user.id
    )
