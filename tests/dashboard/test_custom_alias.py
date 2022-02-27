from flask import url_for, g

from app.alias_utils import delete_alias
from app.config import EMAIL_DOMAIN
from app.dashboard.views.custom_alias import (
    signer,
    verify_prefix_suffix,
    get_available_suffixes,
    AliasSuffix,
)
from app.db import Session
from app.models import (
    Mailbox,
    CustomDomain,
    Alias,
    User,
    DomainDeletedAlias,
    DeletedAlias,
    SLDomain,
)
from app.utils import random_word
from tests.utils import login


def test_add_alias_success(flask_client):
    user = login(flask_client)

    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=f".12345@{EMAIL_DOMAIN}",
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )
    signed_alias_suffix = signer.sign(alias_suffix.serialize()).decode()

    # create with a single mailbox
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": signed_alias_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"Alias prefix.12345@{EMAIL_DOMAIN} has been created" in str(r.data)

    alias = Alias.order_by(Alias.created_at.desc()).first()
    assert not alias._mailboxes


def test_add_alias_multiple_mailboxes(flask_client):
    user = login(flask_client)
    Session.commit()

    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=f".12345@{EMAIL_DOMAIN}",
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )
    signed_alias_suffix = signer.sign(alias_suffix.serialize()).decode()

    # create with a multiple mailboxes
    mb1 = Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Session.commit()

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": signed_alias_suffix,
            "mailboxes": [user.default_mailbox_id, mb1.id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"Alias prefix.12345@{EMAIL_DOMAIN} has been created" in str(r.data)

    alias = Alias.order_by(Alias.created_at.desc()).first()
    assert alias._mailboxes


def test_not_show_unverified_mailbox(flask_client):
    """make sure user unverified mailbox is not shown to user"""
    user = login(flask_client)
    Session.commit()

    Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Mailbox.create(user_id=user.id, email="m2@example.com", verified=False)
    Session.commit()

    r = flask_client.get(url_for("dashboard.custom_alias"))

    assert "m1@example.com" in str(r.data)
    assert "m2@example.com" not in str(r.data)


def test_verify_prefix_suffix(flask_client):
    user = login(flask_client)
    Session.commit()

    CustomDomain.create(user_id=user.id, domain="test.com", ownership_verified=True)

    assert verify_prefix_suffix(user, "prefix", "@test.com")
    assert not verify_prefix_suffix(user, "prefix", "@abcd.com")

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    assert verify_prefix_suffix(user, "prefix", suffix)


def test_available_suffixes(flask_client):
    user = login(flask_client)

    CustomDomain.create(user_id=user.id, domain="test.com", ownership_verified=True)

    assert len(get_available_suffixes(user)) > 0

    # first suffix is custom domain
    first_suffix = get_available_suffixes(user)[0]
    assert first_suffix.is_custom
    assert first_suffix.suffix == "@test.com"
    assert first_suffix.signed_suffix.startswith("@test.com")


def test_available_suffixes_default_domain(flask_client):
    user = login(flask_client)

    sl_domain = SLDomain.first()
    CustomDomain.create(
        user_id=user.id, domain="test.com", ownership_verified=True, commit=True
    )

    user.default_alias_public_domain_id = sl_domain.id

    # first suffix is SL Domain
    first_suffix = get_available_suffixes(user)[0]
    assert first_suffix.suffix.endswith(f"@{sl_domain.domain}")

    user.default_alias_public_domain_id = None
    # first suffix is custom domain
    first_suffix = get_available_suffixes(user)[0]
    assert first_suffix.suffix == "@test.com"


def test_available_suffixes_random_prefix_generation(flask_client):
    user = login(flask_client)

    CustomDomain.create(
        user_id=user.id, domain="test.com", ownership_verified=True, commit=True
    )
    cd2 = CustomDomain.create(
        user_id=user.id, domain="test2.com", ownership_verified=True, commit=True
    )

    user.default_alias_custom_domain_id = cd2.id

    # first suffix is test2.com
    first_suffix = get_available_suffixes(user)[0]
    assert first_suffix.suffix == "@test2.com"

    cd2.random_prefix_generation = True
    # e.g. .meo@test2.com
    first_suffix = get_available_suffixes(user)[0]
    assert first_suffix.suffix.endswith("@test2.com")
    assert first_suffix.suffix.startswith(".")


def test_add_already_existed_alias(flask_client):
    user = login(flask_client)
    Session.commit()

    another_user = User.create(
        email="a2@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"

    alias_suffix = AliasSuffix(
        is_custom=False, suffix=suffix, is_premium=False, domain=EMAIL_DOMAIN
    )
    signed_alias_suffix = signer.sign(alias_suffix.serialize()).decode()

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
            "signed-alias-suffix": signed_alias_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"prefix{suffix} cannot be used" in r.get_data(True)


def test_add_alias_in_global_trash(flask_client):
    user = login(flask_client)
    Session.commit()

    another_user = User.create(
        email="a2@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    alias_suffix = AliasSuffix(
        is_custom=False, suffix=suffix, is_premium=False, domain=EMAIL_DOMAIN
    )
    signed_alias_suffix = signer.sign(alias_suffix.serialize()).decode()

    # delete an alias: alias should go the DeletedAlias
    alias = Alias.create(
        user_id=another_user.id,
        email=f"prefix{suffix}",
        mailbox_id=another_user.default_mailbox_id,
        commit=True,
    )

    assert DeletedAlias.count() == 0
    delete_alias(alias, another_user)
    assert DeletedAlias.count() == 1

    # create the same alias, should return error
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": signed_alias_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"prefix{suffix} cannot be used" in r.get_data(True)


def test_add_alias_in_custom_domain_trash(flask_client):
    user = login(flask_client)

    custom_domain = CustomDomain.create(
        user_id=user.id, domain="ab.cd", ownership_verified=True, commit=True
    )

    # delete a custom-domain alias: alias should go the DomainDeletedAlias
    alias = Alias.create(
        user_id=user.id,
        email="prefix@ab.cd",
        custom_domain_id=custom_domain.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    assert DomainDeletedAlias.count() == 0
    delete_alias(alias, user)
    assert DomainDeletedAlias.count() == 1

    # create the same alias, should return error
    suffix = "@ab.cd"

    alias_suffix = AliasSuffix(
        is_custom=False, suffix=suffix, is_premium=False, domain=EMAIL_DOMAIN
    )
    signed_alias_suffix = signer.sign(alias_suffix.serialize()).decode()

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": signed_alias_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "You have deleted this alias before. You can restore it on" in r.get_data(
        True
    )


def test_too_many_requests(flask_client):
    user = login(flask_client)

    # create a custom domain
    CustomDomain.create(user_id=user.id, domain="ab.cd", verified=True, commit=True)

    # can't create more than 5 aliases in 1 minute
    for i in range(7):
        signed_suffix = signer.sign("@ab.cd").decode()

        r = flask_client.post(
            url_for("dashboard.custom_alias"),
            data={
                "prefix": f"prefix{i}",
                "suffix": signed_suffix,
                "mailboxes": [user.default_mailbox_id],
            },
            follow_redirects=True,
        )

        # to make flask-limiter work with unit test
        # https://github.com/alisaifee/flask-limiter/issues/147#issuecomment-642683820
        g._rate_limiting_complete = False
    else:
        # last request
        assert r.status_code == 429
        assert "Whoa, slow down there, pardner!" in str(r.data)
