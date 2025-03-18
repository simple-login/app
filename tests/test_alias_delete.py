from typing import List, Optional

import arrow
import pytest

from app import config
from app.alias_audit_log_utils import AliasAuditLogAction
from app.alias_delete import delete_alias, restore_all_alias, clear_trash
from app.alias_delete import perform_alias_deletion, move_alias_to_trash, restore_alias
from app.db import Session
from app.errors import CannotCreateAliasQuotaExceeded
from app.events.event_dispatcher import GlobalDispatcher
from app.models import (
    UserAliasDeleteAction,
    Alias,
    AliasDeleteReason,
    AliasAuditLog,
    DeletedAlias,
    Mailbox,
    PartnerUser,
)
from tests.events.event_test_utils import (
    OnMemoryDispatcher,
    _get_event_from_string,
    _create_linked_user,
)
from tests.utils import create_new_user

on_memory_dispatcher = OnMemoryDispatcher()


def setup_module():
    GlobalDispatcher.set_dispatcher(on_memory_dispatcher)
    config.EVENT_WEBHOOK = "http://test"


def teardown_module():
    GlobalDispatcher.set_dispatcher(None)
    config.EVENT_WEBHOOK = None


def ensure_alias_is_trashed(
    alias: Alias, expected_audit_log_size: int, reason: AliasDeleteReason
):
    assert alias.enabled is False
    assert alias.delete_on is not None
    assert alias.delete_reason == reason

    # Ensure audit log
    audit_logs: List[AliasAuditLog] = AliasAuditLog.filter_by(alias_id=alias.id).all()
    assert len(audit_logs) == expected_audit_log_size
    assert (
        audit_logs[expected_audit_log_size - 2].action
        == AliasAuditLogAction.CreateAlias.value
    )
    assert (
        audit_logs[expected_audit_log_size - 1].action
        == AliasAuditLogAction.TrashAlias.value
    )

    # Ensure DeletedAlias instance is not created
    deleted_alias: Optional[DeletedAlias] = DeletedAlias.get_by(email=alias.email)
    assert deleted_alias is None


def ensure_alias_is_deleted(
    alias_id: int,
    alias_email: str,
    expected_audit_log_size: int,
    reason: AliasDeleteReason,
):
    # Ensure audit log
    audit_logs: List[AliasAuditLog] = AliasAuditLog.filter_by(alias_id=alias_id).all()
    assert len(audit_logs) == expected_audit_log_size
    assert (
        audit_logs[expected_audit_log_size - 1].action
        == AliasAuditLogAction.DeleteAlias.value
    )

    # Make sure it's not on the db
    db_alias = Alias.get_by(id=alias_id)
    assert db_alias is None

    # Make sure the DeletedAlias instance is created
    deleted_alias: Optional[DeletedAlias] = DeletedAlias.get_by(email=alias_email)
    assert deleted_alias is not None
    assert deleted_alias.reason == reason


# Delete alias
def test_delete_alias_twice_performs_alias_deletion():
    user = create_new_user(alias_delete_action=UserAliasDeleteAction.MoveToTrash)
    alias = Alias.create_new_random(user)
    alias_id = alias.id
    alias_email = alias.email
    assert alias.delete_on is None

    # This one should move to trash
    reason = AliasDeleteReason.ManualAction
    delete_alias(alias, user, reason=reason, commit=True)
    ensure_alias_is_trashed(alias, 2, reason)

    # This one should delete it
    delete_alias(alias, user, commit=True)
    ensure_alias_is_deleted(alias_id, alias_email, 3, reason)


def test_delete_alias_with_user_action_set_to_delete():
    user = create_new_user(alias_delete_action=UserAliasDeleteAction.DeleteImmediately)
    alias = Alias.create_new_random(user)
    alias_id = alias.id
    alias_email = alias.email
    assert alias.delete_on is None

    reason = AliasDeleteReason.ManualAction
    delete_alias(alias, user, reason=reason, commit=True)
    ensure_alias_is_deleted(alias_id, alias_email, 2, reason)


# perform_alias_deletion
def test_perform_alias_deletion():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    alias_id = alias.id
    alias_email = alias.email
    assert alias.delete_on is None

    reason = AliasDeleteReason.ManualAction
    perform_alias_deletion(alias, user, reason=reason, commit=True)
    ensure_alias_is_deleted(alias_id, alias_email, 2, reason)


# move_alias_to_trash
def test_move_alias_to_trash():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    assert alias.delete_on is None

    reason = AliasDeleteReason.ManualAction
    move_alias_to_trash(alias, user, reason=reason, commit=True)
    ensure_alias_is_trashed(alias, 2, reason)


# delete mailbox
def generate_user_setting() -> List[UserAliasDeleteAction]:
    return [UserAliasDeleteAction.DeleteImmediately, UserAliasDeleteAction.MoveToTrash]


@pytest.mark.parametrize("user_setting", generate_user_setting())
def test_delete_mailbox_deletes_alias_with_user_setting(
    user_setting: UserAliasDeleteAction
):
    user = create_new_user(alias_delete_action=user_setting)
    mb = Mailbox.create(user_id=user.id, email="ab1@cd.com", verified=True)
    alias = Alias.create_new_random(user)
    alias.mailbox_id = mb.id
    Session.commit()
    assert alias.delete_on is None
    alias_id = alias.id
    alias_email = alias.email

    Mailbox.delete(mb.id)

    ensure_alias_is_deleted(
        alias_id, alias_email, 2, reason=AliasDeleteReason.MailboxDeleted
    )


# Restore alias
def check_alias_has_been_restored(alias_id: int, user_pu: PartnerUser):
    alias = Alias.get(alias_id)
    assert alias.delete_on is None
    assert alias.delete_reason is None
    assert alias.enabled
    # audit log
    audit_log = (
        AliasAuditLog.get_by(user_id=user_pu.user_id, alias_id=alias.id)
        .order_by(AliasAuditLog.id.desc())
        .first()
    )
    assert audit_log is not None
    assert audit_log.action == AliasAuditLogAction.RestoreAlias.value
    # create event
    assert len(on_memory_dispatcher.memory) > 0
    found = False
    for event_data in on_memory_dispatcher.memory:
        event_content = _get_event_from_string(event_data, user_pu.user, user_pu)
        if event_content.alias_created is None:
            continue
        alias_created = event_content.alias_created
        if alias_created.id != alias.id:
            continue
        found = True
        assert alias.email == alias_created.email
        assert alias.note or "" == alias_created.note
        assert alias.enabled == alias_created.enabled
    assert found


def test_restore_one_alias():
    (user, user_pu) = _create_linked_user()
    alias1 = Alias.create_new_random(user)
    alias1.delete_on = arrow.now().shift(minutes=6)
    alias1.delete_reason = AliasDeleteReason.Unspecified
    alias1.enabled = False
    alias2 = Alias.create_new_random(user)
    alias2.delete_on = arrow.now().shift(minutes=10)
    alias2.delete_reason = AliasDeleteReason.Unspecified
    alias2.enabled = False
    Session.commit()
    on_memory_dispatcher.clear()
    restore_alias(user, alias2.id)
    new_alias_1 = Alias.get(alias1.id)
    assert new_alias_1.delete_on is not None
    assert new_alias_1.delete_reason is not None
    assert not new_alias_1.enabled
    check_alias_has_been_restored(alias2.id, user_pu)


# Restore all alias
def test_restore_all_alias():
    (user, user_pu) = _create_linked_user()
    alias1 = Alias.create_new_random(user)
    alias1.delete_on = arrow.now().shift(minutes=6)
    alias1.delete_reason = AliasDeleteReason.Unspecified
    alias1.enabled = False
    alias2 = Alias.create_new_random(user)
    alias2.delete_on = arrow.now().shift(minutes=10)
    alias2.delete_reason = AliasDeleteReason.Unspecified
    alias2.enabled = False
    Session.commit()
    on_memory_dispatcher.clear()
    count = restore_all_alias(user)
    assert count == 2
    check_alias_has_been_restored(alias1.id, user_pu)
    check_alias_has_been_restored(alias2.id, user_pu)


def test_clear_trash():
    (user, user_pu) = _create_linked_user()
    alias1 = Alias.create_new_random(user)
    alias2 = Alias.create_new_random(user)
    alias2.delete_on = arrow.now().shift(days=10)
    alias2.delete_reason = AliasDeleteReason.MailboxDeleted
    Session.commit()
    on_memory_dispatcher.clear()
    count = clear_trash(user)
    assert count == 1
    db_alias = Alias.get_by(id=alias1.id)
    assert db_alias is not None
    assert db_alias.delete_on is None
    db_alias = Alias.get_by(id=alias2.id)
    assert db_alias is None
    deleted_alias = DeletedAlias.get_by(email=alias2.email)
    assert deleted_alias is not None
    assert deleted_alias.reason == AliasDeleteReason.MailboxDeleted


def test_cannot_restore_single_alias_if_over_quota():
    user = create_new_user()

    # Max out aliases
    aliases = []
    while user.can_create_new_alias():
        aliases.append(Alias.create_new_random(user))

    # Trash one alias
    alias_to_trash = aliases[0]
    move_alias_to_trash(alias_to_trash, user)

    # Create new alias
    Alias.create_new_random(user)

    # Try to restore trashed alias
    with pytest.raises(CannotCreateAliasQuotaExceeded):
        restore_alias(user, alias_to_trash.id)


def test_can_restore_single_alias_just_to_quota():
    user = create_new_user()

    # Max out aliases
    aliases = []
    while user.can_create_new_alias():
        aliases.append(Alias.create_new_random(user))

    # Trash one alias
    alias_to_trash = aliases[0]
    move_alias_to_trash(alias_to_trash, user)

    # Create new alias
    new_alias = Alias.create_new_random(user)

    # Trash that alias too
    move_alias_to_trash(new_alias, user)

    # Restore first alias
    restored_alias = restore_alias(user, alias_to_trash.id)
    assert restored_alias is not None
    assert restored_alias.id == alias_to_trash.id

    assert restored_alias.delete_on is None
    assert restored_alias.delete_reason is None


def test_cannot_restore_many_aliases_over_quota():
    user = create_new_user()

    # Max out aliases
    aliases = []
    while user.can_create_new_alias():
        aliases.append(Alias.create_new_random(user))

    # Trash two aliases
    alias_to_trash1 = aliases[0]
    move_alias_to_trash(alias_to_trash1, user)
    alias_to_trash2 = aliases[1]
    move_alias_to_trash(alias_to_trash2, user)

    # Create new alias
    Alias.create_new_random(user)

    # Try to restore trashed aliases
    with pytest.raises(CannotCreateAliasQuotaExceeded):
        restore_all_alias(user)


def test_can_restore_many_aliases_just_to_quota():
    user = create_new_user()

    # Max out aliases
    aliases = []
    while user.can_create_new_alias():
        aliases.append(Alias.create_new_random(user))

    # Trash two aliases
    alias_to_trash1 = aliases[0]
    move_alias_to_trash(alias_to_trash1, user)
    alias_to_trash2 = aliases[1]
    move_alias_to_trash(alias_to_trash2, user)

    count = restore_all_alias(user)
    assert count == 2
