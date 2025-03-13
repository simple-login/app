import pytest

from app.alias_audit_log_utils import AliasAuditLogAction
from app.alias_utils import delete_alias
from app.alias_actions import perform_alias_deletion, move_alias_to_trash
from app.db import Session
from app.models import (
    UserAliasDeleteAction,
    Alias,
    AliasDeleteReason,
    AliasAuditLog,
    DeletedAlias,
    Mailbox,
)
from tests.utils import create_new_user
from typing import List, Optional


def ensure_alias_is_trashed(
    alias: Alias, expected_audit_log_size: int, reason: AliasDeleteReason
):
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
