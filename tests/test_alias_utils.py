from typing import List

from app.alias_utils import (
    delete_alias,
    check_alias_prefix,
    get_user_if_alias_would_auto_create,
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
)
from tests.utils import create_new_user, random_domain, random_token


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
