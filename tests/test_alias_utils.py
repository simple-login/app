from typing import List

from app.alias_delete import delete_alias
from app.alias_utils import (
    check_alias_prefix,
    get_user_if_alias_would_auto_create,
    get_alias_recipient_name,
    try_auto_create,
)
from app.config import ALIAS_DOMAINS
from app.db import Session
from app.models import (
    Alias,
    DeletedAlias,
    CustomDomain,
    AutoCreateRule,
    Directory,
    DirectoryMailbox,
    User,
    DomainDeletedAlias,
)
from app.utils import random_string
from tests.utils import create_new_user, random_domain, random_token, random_email


def test_delete_alias(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    assert Alias.get_by(email=alias.email)

    delete_alias(alias, user)
    assert Alias.get_by(email=alias.email) is None
    assert DeletedAlias.get_by(email=alias.email)


def test_delete_alias_already_in_trash(flask_client):
    """delete an alias that's already in alias trash"""
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()

    # add the alias to global trash
    Session.add(DeletedAlias(email=alias.email))
    Session.commit()

    delete_alias(alias, user)
    assert Alias.get_by(email=alias.email) is None


def test_check_alias_prefix(flask_client):
    assert check_alias_prefix("ab-cd_")
    assert not check_alias_prefix("")
    assert not check_alias_prefix("éè")
    assert not check_alias_prefix("a b")
    assert not check_alias_prefix("+👌")
    assert not check_alias_prefix("too-long" * 10)


def get_auto_create_alias_tests(user: User) -> List:
    user.lifetime = True
    catchall = CustomDomain.create(
        user_id=user.id,
        catch_all=True,
        domain=random_domain(),
        verified=True,
        flush=True,
    )
    no_catchall = CustomDomain.create(
        user_id=user.id,
        catch_all=False,
        domain=random_domain(),
        verified=True,
        flush=True,
    )
    no_catchall_with_rule = CustomDomain.create(
        user_id=user.id,
        catch_all=False,
        domain=random_domain(),
        verified=True,
        flush=True,
    )
    AutoCreateRule.create(
        custom_domain_id=no_catchall_with_rule.id,
        order=0,
        regex="ok-.*",
        flush=True,
    )
    deleted_alias = f"deletedalias@{catchall.domain}"
    Session.add(
        DomainDeletedAlias(email=deleted_alias, domain_id=catchall.id, user_id=user.id)
    )
    Session.flush()
    dir_name = random_token()
    directory = Directory.create(name=dir_name, user_id=user.id, flush=True)
    DirectoryMailbox.create(
        directory_id=directory.id, mailbox_id=user.default_mailbox_id, flush=True
    )
    Session.commit()

    return [
        (f"nonexistant@{catchall.domain}", True),
        (f"nonexistant@{no_catchall.domain}", False),
        (f"nonexistant@{no_catchall_with_rule.domain}", False),
        (f"ok-nonexistant@{no_catchall_with_rule.domain}", True),
        (f"{dir_name}+something@nowhere.net", False),
        (f"{dir_name}#something@nowhere.net", False),
        (f"{dir_name}/something@nowhere.net", False),
        (f"{dir_name}+something@{ALIAS_DOMAINS[0]}", True),
        (f"{dir_name}#something@{ALIAS_DOMAINS[0]}", True),
        (f"{dir_name}/something@{ALIAS_DOMAINS[0]}", True),
        (deleted_alias, False),
    ]


def test_get_user_if_alias_would_auto_create(flask_client):
    user = create_new_user()
    for test_id, (address, expected_ok) in enumerate(get_auto_create_alias_tests(user)):
        result = get_user_if_alias_would_auto_create(address)
        if expected_ok:
            assert (
                isinstance(result, User) and result.id == user.id
            ), f"Case {test_id} - Failed address {address}"
        else:
            assert not result, f"Case {test_id} - Failed address {address}"


def test_auto_create_alias(flask_client):
    user = create_new_user()
    for test_id, (address, expected_ok) in enumerate(get_auto_create_alias_tests(user)):
        result = try_auto_create(address)
        if expected_ok:
            assert result, f"Case {test_id} - Failed address {address}"
        else:
            assert result is None, f"Case {test_id} - Failed address {address}"


# get_alias_recipient_name
def test_get_alias_recipient_name_no_overrides():
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    res = get_alias_recipient_name(alias)
    assert res.message is None
    assert res.name == alias.email


def test_get_alias_recipient_name_alias_name():
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        name=random_string(),
        commit=True,
    )
    res = get_alias_recipient_name(alias)
    assert res.message is not None
    assert res.name == f"{alias.name} <{alias.email}>"


def test_get_alias_recipient_alias_with_name_and_custom_domain_name():
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_domain(),
        name=random_string(),
        verified=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        name=random_string(),
        custom_domain_id=custom_domain.id,
        commit=True,
    )
    res = get_alias_recipient_name(alias)
    assert res.message is not None
    assert res.name == f"{alias.name} <{alias.email}>"


def test_get_alias_recipient_alias_without_name_and_custom_domain_without_name():
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_domain(),
        verified=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        custom_domain_id=custom_domain.id,
        commit=True,
    )
    res = get_alias_recipient_name(alias)
    assert res.message is None
    assert res.name == alias.email


def test_get_alias_recipient_alias_without_name_and_custom_domain_name():
    user = create_new_user()
    custom_domain = CustomDomain.create(
        user_id=user.id,
        domain=random_domain(),
        name=random_string(),
        verified=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        custom_domain_id=custom_domain.id,
        commit=True,
    )
    res = get_alias_recipient_name(alias)
    assert res.message is not None
    assert res.name == f"{custom_domain.name} <{alias.email}>"
