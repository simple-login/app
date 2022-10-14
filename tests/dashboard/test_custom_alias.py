from random import random

from flask import url_for, g

from app import config
from app.alias_suffix import (
    get_alias_suffixes,
    AliasSuffix,
    signer,
    verify_prefix_suffix,
)
from app.alias_utils import delete_alias
from app.config import EMAIL_DOMAIN
from app.db import Session
from app.models import (
    Mailbox,
    CustomDomain,
    Alias,
    DomainDeletedAlias,
    DeletedAlias,
    SLDomain,
    DailyMetric,
)
from app.utils import random_word
from tests.utils import login, random_domain, create_new_user


def test_add_alias_success(flask_client):
    user = login(flask_client)

    suffix = f".{int(random() * 100000)}@{EMAIL_DOMAIN}"
    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=suffix,
        signed_suffix=signer.sign(suffix).decode(),
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )

    # create with a single mailbox
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": alias_suffix.signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"Alias prefix{alias_suffix.suffix} has been created" in str(r.data)

    alias = Alias.order_by(Alias.created_at.desc()).first()
    assert not alias._mailboxes


def test_add_alias_increment_nb_daily_metric_alias(flask_client):
    user = login(flask_client)

    daily_metric = DailyMetric.get_or_create_today_metric()
    Session.commit()
    nb_alias = daily_metric.nb_alias

    suffix = f".{int(random() * 100000)}@{EMAIL_DOMAIN}"
    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=suffix,
        signed_suffix=signer.sign(suffix).decode(),
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )

    # create with a single mailbox
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": alias_suffix.signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    new_daily_metric = DailyMetric.get_or_create_today_metric()
    assert new_daily_metric.nb_alias == nb_alias + 1


def test_add_alias_multiple_mailboxes(flask_client):
    user = login(flask_client)
    Session.commit()

    suffix = f".{int(random() * 100000)}@{EMAIL_DOMAIN}"
    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=suffix,
        signed_suffix=signer.sign(suffix).decode(),
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )

    # create with a multiple mailboxes
    mb1 = Mailbox.create(user_id=user.id, email="m1@example.com", verified=True)
    Session.commit()

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": alias_suffix.signed_suffix,
            "mailboxes": [user.default_mailbox_id, mb1.id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"Alias prefix{alias_suffix.suffix} has been created" in str(r.data)

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

    assert len(get_alias_suffixes(user)) > 0

    # first suffix is custom domain
    first_suffix = get_alias_suffixes(user)[0]
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
    first_suffix = get_alias_suffixes(user)[0]
    assert first_suffix.suffix.endswith(f"@{sl_domain.domain}")

    user.default_alias_public_domain_id = None
    # first suffix is custom domain
    first_suffix = get_alias_suffixes(user)[0]
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
    first_suffix = get_alias_suffixes(user)[0]
    assert first_suffix.suffix == "@test2.com"

    cd2.random_prefix_generation = True
    # e.g. .meo@test2.com
    first_suffix = get_alias_suffixes(user)[0]
    assert first_suffix.suffix.endswith("@test2.com")
    assert first_suffix.suffix.startswith(".")


def test_available_suffixes_hidden_domain(flask_client):
    user = login(flask_client)
    nb_suffix = len(get_alias_suffixes(user))

    sl_domain = SLDomain.create(domain=random_domain(), commit=True)
    assert len(get_alias_suffixes(user)) == nb_suffix + 1

    sl_domain.hidden = True
    Session.commit()
    assert len(get_alias_suffixes(user)) == nb_suffix


def test_available_suffixes_domain_order(flask_client):
    user = login(flask_client)

    domain = random_domain()
    # will be the last domain as other domains have order=0
    sl_domain = SLDomain.create(domain=domain, order=1, commit=True)
    last_suffix_info = get_alias_suffixes(user)[-1]
    assert last_suffix_info.suffix.endswith(domain)

    # now will be the first domain
    sl_domain.order = -1
    Session.commit()
    first_suffix_info = get_alias_suffixes(user)[0]
    assert first_suffix_info.suffix.endswith(domain)


def test_add_already_existed_alias(flask_client):
    user = login(flask_client)
    Session.commit()

    another_user = create_new_user()

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"

    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=suffix,
        signed_suffix=signer.sign(suffix).decode(),
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )

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
            "signed-alias-suffix": alias_suffix.signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"prefix{suffix} cannot be used" in r.get_data(True)


def test_add_alias_in_global_trash(flask_client):
    user = login(flask_client)
    Session.commit()

    another_user = create_new_user()

    word = random_word()
    suffix = f".{word}@{EMAIL_DOMAIN}"
    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=suffix,
        signed_suffix=signer.sign(suffix).decode(),
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )

    # delete an alias: alias should go the DeletedAlias
    alias = Alias.create(
        user_id=another_user.id,
        email=f"prefix{suffix}",
        mailbox_id=another_user.default_mailbox_id,
        commit=True,
    )

    prev_deleted = DeletedAlias.count()
    delete_alias(alias, another_user)
    assert prev_deleted + 1 == DeletedAlias.count()

    # create the same alias, should return error
    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": alias_suffix.signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert f"prefix{suffix} cannot be used" in r.get_data(True)


def test_add_alias_in_custom_domain_trash(flask_client):
    user = login(flask_client)

    domain = random_domain()
    custom_domain = CustomDomain.create(
        user_id=user.id, domain=domain, ownership_verified=True, commit=True
    )

    # delete a custom-domain alias: alias should go the DomainDeletedAlias
    alias = Alias.create(
        user_id=user.id,
        email=f"prefix@{domain}",
        custom_domain_id=custom_domain.id,
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    assert DomainDeletedAlias.count() == 0
    delete_alias(alias, user)
    assert DomainDeletedAlias.count() == 1

    # create the same alias, should return error
    suffix = f"@{domain}"

    alias_suffix = AliasSuffix(
        is_custom=False,
        suffix=suffix,
        signed_suffix=signer.sign(suffix).decode(),
        is_premium=False,
        domain=EMAIL_DOMAIN,
    )

    r = flask_client.post(
        url_for("dashboard.custom_alias"),
        data={
            "prefix": "prefix",
            "signed-alias-suffix": alias_suffix.signed_suffix,
            "mailboxes": [user.default_mailbox_id],
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "You have deleted this alias before. You can restore it on" in r.get_data(
        True
    )


def test_too_many_requests(flask_client):
    config.DISABLE_RATE_LIMIT = False
    user = login(flask_client)

    # create a custom domain
    domain = random_domain()
    CustomDomain.create(user_id=user.id, domain=domain, verified=True, commit=True)

    # can't create more than 5 aliases in 1 minute
    for i in range(7):
        signed_suffix = signer.sign(f"@{domain}").decode()

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
