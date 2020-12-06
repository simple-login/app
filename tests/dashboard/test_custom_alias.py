from flask import url_for

from app.alias_utils import delete_alias
from app.config import EMAIL_DOMAIN
from app.dashboard.views.custom_alias import (
    signer,
    verify_prefix_suffix,
    available_suffixes,
)
from app.extensions import db
from app.models import (
    Mailbox,
    CustomDomain,
    Alias,
    User,
    DomainDeletedAlias,
    DeletedAlias,
)
from app.utils import random_word
from tests.utils import login


def test_add_alias_success(flask_client):
    user = login(flask_client)
    db.session.commit()

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    suffix = signer.sign(suffix).decode()

    # create with a single mailbox
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "suffix": suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"Alias prefix.{word}@{EMAIL_DOMAIN} has been created" in str(r.data)

    alias = Alias.query.order_by(Alias.created_at.desc()).first()
    assert not alias._mailboxes


def test_add_alias_multiple_mailboxes(flask_client):
    user = login(flask_client)
    db.session.commit()

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    suffix = signer.sign(suffix).decode()

    # create with a multiple mailboxes
    mb1 = Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    db.session.commit()

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "suffix": suffix,
            "mailboxes": [user.default_mailbox_id, mb1.id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"Alias prefix.{word}@{EMAIL_DOMAIN} has been created" in str(r.data)

    alias = Alias.query.order_by(Alias.created_at.desc()).first()
    assert alias._mailboxes


def test_not_show_unverified_mailbox(flask_client):
    """make sure user unverified mailbox is not shown to user"""
    user = login(flask_client)
    db.session.commit()

    Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Mailbox.create(user_id=user.id, email="m2@example.com", verified=False)
    db.session.commit()

    r = flask_client.get(url_for("dashboard.custom_alias"))

    assert "m1@example.com" in str(r.data)
    assert "m2@example.com" not in str(r.data)


def test_verify_prefix_suffix(flask_client):
    user = login(flask_client)
    db.session.commit()

    CustomDomain.create(user_id=user.id, domain="test.com", verified=True)

    assert verify_prefix_suffix(user, "prefix", "@test.com")
    assert not verify_prefix_suffix(user, "prefix", "@abcd.com")

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    assert verify_prefix_suffix(user, "prefix", suffix)


def test_available_suffixes(flask_client):
    user = login(flask_client)
    db.session.commit()

    CustomDomain.create(user_id=user.id, domain="test.com", verified=True)

    assert len(available_suffixes(user)) > 0

    # first suffix is custom domain
    first_suffix = available_suffixes(user)[0]
    assert first_suffix[0]
    assert first_suffix[1] == "@test.com"
    assert first_suffix[2].startswith("@test.com")


def test_add_already_existed_alias(flask_client):
    user = login(flask_client)
    db.session.commit()

    another_user = User.create(
        email="a2@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    signed_suffix = signer.sign(suffix).decode()

    # alias already exist
    Alias.create(
        user_id=another_user.id,
        email=f"prefix{suffix}",
        mailbox_id=another_user.default_mailbox_id,
        commit=True,
    )

    # create the same alias, should return error
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "suffix": signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"prefix{suffix} cannot be used" in r.get_data(True)


def test_add_alias_in_global_trash(flask_client):
    user = login(flask_client)
    db.session.commit()

    another_user = User.create(
        email="a2@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    signed_suffix = signer.sign(suffix).decode()

    # delete an alias: alias should go the DeletedAlias
    alias = Alias.create(
        user_id=another_user.id,
        email=f"prefix{suffix}",
        mailbox_id=another_user.default_mailbox_id,
        commit=True,
    )

    assert DeletedAlias.query.count() == 0
    delete_alias(alias, another_user)
    assert DeletedAlias.query.count() == 1

    # create the same alias, should return error
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "suffix": signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"prefix{suffix} cannot be used" in r.get_data(True)


def test_add_alias_in_custom_domain_trash(flask_client):
    user = login(flask_client)
    db.session.commit()

    custom_domain = CustomDomain.create(
        user_id=user.id, domain="ab.cd", verified=True, commit=True
    )

    # delete a custom-domain alias: alias should go the DomainDeletedAlias
    alias = Alias.create(
        user_id=user.id,
        email="prefix@ab.cd",
        custom_domain_id=custom_domain.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    assert DomainDeletedAlias.query.count() == 0
    delete_alias(alias, user)
    assert DomainDeletedAlias.query.count() == 1

    # create the same alias, should return error
    suffix = "@ab.cd"
    signed_suffix = signer.sign(suffix).decode()
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "suffix": signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "You have deleted this alias before. You can restore it on" in r.get_data(
        True
    )
