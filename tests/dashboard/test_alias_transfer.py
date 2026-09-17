import app.alias_utils
import arrow
from app import config
from app.db import Session
from app.dashboard.views.alias_transfer import hmac_alias_transfer_token
from app.events.event_dispatcher import GlobalDispatcher
from app.models import (
    Alias,
    AuthorizationCode,
    Client,
    ClientUser,
    Mailbox,
    AliasMailbox,
    OauthToken,
    RedirectUri,
)
from tests.events.event_test_utils import (
    OnMemoryDispatcher,
    _get_event_from_string,
    _create_linked_user,
)
from tests.utils import create_new_user, login, random_domain, random_email
from app.models import User
from app.utils import random_string
from flask import url_for

on_memory_dispatcher = OnMemoryDispatcher()


def setup_module():
    GlobalDispatcher.set_dispatcher(on_memory_dispatcher)
    config.EVENT_WEBHOOK = "http://test"


def teardown_module():
    GlobalDispatcher.set_dispatcher(None)
    config.EVENT_WEBHOOK = None


def test_alias_transfer(flask_client):
    (source_user, source_user_pu) = _create_linked_user()
    source_user = login(flask_client, source_user)
    mb = Mailbox.create(user_id=source_user.id, email="mb@gmail.com", commit=True)

    alias = Alias.create_new_random(source_user)
    Session.commit()

    AliasMailbox.create(alias_id=alias.id, mailbox_id=mb.id, commit=True)

    (target_user, target_user_pu) = _create_linked_user()

    Mailbox.create(
        user_id=target_user.id, email="hey2@example.com", verified=True, commit=True
    )

    on_memory_dispatcher.clear()
    app.alias_utils.transfer_alias(alias, target_user, target_user.mailboxes())

    # refresh from db
    alias = Alias.get(alias.id)
    assert alias.user == target_user
    assert set(alias.mailboxes) == set(target_user.mailboxes())
    assert len(alias.mailboxes) == 2

    # Check events
    assert len(on_memory_dispatcher.memory) == 2
    # 1st delete event
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, source_user, source_user_pu)
    assert event_content.alias_deleted is not None
    alias_deleted = event_content.alias_deleted
    assert alias_deleted.id == alias.id
    assert alias_deleted.email == alias.email
    # 2nd create event
    event_data = on_memory_dispatcher.memory[1]
    event_content = _get_event_from_string(event_data, target_user, target_user_pu)
    assert event_content.alias_created is not None
    alias_created = event_content.alias_created
    assert alias.id == alias_created.id
    assert alias.email == alias_created.email
    assert alias.note or "" == alias_created.note
    assert alias.enabled == alias_created.enabled


def _create_oauth_client(user) -> Client:
    client = Client.create_new("test client", user.id)
    Session.commit()
    RedirectUri.create(
        client_id=client.id, uri=f"https://{random_domain()}/callback", commit=True
    )
    return client


def _create_user_with_mailbox() -> User:
    user = create_new_user()
    Mailbox.create(user_id=user.id, email=random_email(), verified=True, commit=True)
    Session.commit()
    return user


def _start_transfer(alias) -> str:
    """prepare a transfer link for an alias and return the plain token"""
    transfer_token = f"{alias.id}.{random_string()}"
    alias.transfer_token = hmac_alias_transfer_token(transfer_token)
    alias.transfer_token_expiration = arrow.utcnow().shift(hours=1)
    Session.commit()
    return transfer_token


def test_alias_transfer_does_not_transfer_oidc_identity(flask_client):
    """
    An alias used with "Sign in with SimpleLogin" must not carry its OIDC
    identity (= ClientUser row, whose id is the `sub` claim) over to the user
    that receives the alias.
    """
    source_user = _create_user_with_mailbox()
    alias = Alias.create_new_random(source_user)
    client = _create_oauth_client(source_user)
    client_user = ClientUser.create(
        user_id=source_user.id, client_id=client.id, alias_id=alias.id, commit=True
    )
    original_sub = client_user.get_user_info()["sub"]
    # outstanding grants issued for that identity
    OauthToken.create(
        client_id=client.id,
        user_id=source_user.id,
        access_token=random_string(40),
        commit=True,
    )
    AuthorizationCode.create(
        client_id=client.id,
        user_id=source_user.id,
        code=random_string(),
        commit=True,
    )

    target_user = _create_user_with_mailbox()

    transfer_token = _start_transfer(alias)
    login(flask_client, target_user)
    r = flask_client.post(
        url_for("dashboard.alias_transfer_receive_route", token=transfer_token),
        data={"mailbox_ids": str(target_user.default_mailbox_id)},
        follow_redirects=False,
    )
    assert r.status_code == 302
    Session.expire_all()

    assert Alias.get(alias.id).user_id == target_user.id
    # the previous owner OIDC identity is gone, together with its grants
    assert ClientUser.get(client_user.id) is None
    assert ClientUser.filter_by(alias_id=alias.id).count() == 0
    assert OauthToken.get_by(client_id=client.id, user_id=source_user.id) is None
    assert AuthorizationCode.get_by(client_id=client.id, user_id=source_user.id) is None
    # and nothing has been handed over to the recipient
    assert ClientUser.get_by(client_id=client.id, user_id=target_user.id) is None

    redirect_uri = client.redirect_uris[0].uri

    # the recipient has to give consent again, ie no silent authorization
    r = flask_client.get(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="state",
            redirect_uri=redirect_uri,
            response_type="code",
            scope="openid email",
        ),
        follow_redirects=False,
    )
    assert r.status_code == 200

    # once the recipient allows the client, it gets a *new* identity, with a new sub
    r = flask_client.post(
        url_for(
            "oauth.authorize",
            client_id=client.oauth_client_id,
            state="state",
            redirect_uri=redirect_uri,
            response_type="code",
            scope="openid email",
        ),
        data={
            "suggested-email": target_user.email,
            "suggested-name": target_user.name,
            "button": "allow",
        },
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert r.location.startswith(redirect_uri)
    new_client_user = ClientUser.get_by(client_id=client.id, user_id=target_user.id)
    assert new_client_user is not None
    assert new_client_user.id != client_user.id
    assert new_client_user.get_user_info()["sub"] != original_sub


def test_alias_transfer_when_receiver_uses_same_client(flask_client):
    """
    Transferring an alias linked to a client that the recipient already uses
    must not fail because of the client_user unique constraint.
    """
    source_user = _create_user_with_mailbox()
    alias = Alias.create_new_random(source_user)
    client = _create_oauth_client(source_user)
    source_client_user = ClientUser.create(
        user_id=source_user.id, client_id=client.id, alias_id=alias.id, commit=True
    )

    target_user = _create_user_with_mailbox()
    target_alias = Alias.create_new_random(target_user)
    target_client_user = ClientUser.create(
        user_id=target_user.id,
        client_id=client.id,
        alias_id=target_alias.id,
        commit=True,
    )

    transfer_token = _start_transfer(alias)
    login(flask_client, target_user)
    r = flask_client.post(
        url_for("dashboard.alias_transfer_receive_route", token=transfer_token),
        data={"mailbox_ids": str(target_user.default_mailbox_id)},
        follow_redirects=False,
    )
    assert r.status_code == 302
    Session.expire_all()

    assert Alias.get(alias.id).user_id == target_user.id
    # the previous owner identity is revoked...
    assert ClientUser.get(source_client_user.id) is None
    # ...and the recipient keeps its own identity
    kept = ClientUser.get(target_client_user.id)
    assert kept is not None
    assert kept.user_id == target_user.id
