import random

from app.alias_delete import delete_alias
from app.alias_audit_log_utils import emit_alias_audit_log, AliasAuditLogAction
from app.alias_utils import transfer_alias
from app.models import Alias, AliasAuditLog, AliasDeleteReason
from app.utils import random_string
from tests.utils import create_new_user, random_email


def test_emit_alias_audit_log_for_random_data():
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
    )

    random_user_id = random.randint(1000, 2000)
    message = random_string()
    action = AliasAuditLogAction.ChangeAliasStatus
    emit_alias_audit_log(
        alias=alias,
        user_id=random_user_id,
        action=action,
        message=message,
        commit=True,
    )

    logs_for_alias = AliasAuditLog.filter_by(alias_id=alias.id).all()
    assert len(logs_for_alias) == 2

    last_log = logs_for_alias[-1]
    assert last_log.alias_id == alias.id
    assert last_log.alias_email == alias.email
    assert last_log.user_id == random_user_id
    assert last_log.action == action.value
    assert last_log.message == message


def test_emit_alias_audit_log_on_alias_creation():
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
    )

    log_for_alias = AliasAuditLog.filter_by(alias_id=alias.id).all()
    assert len(log_for_alias) == 1
    assert log_for_alias[0].alias_id == alias.id
    assert log_for_alias[0].alias_email == alias.email
    assert log_for_alias[0].user_id == user.id
    assert log_for_alias[0].action == AliasAuditLogAction.CreateAlias.value


def test_alias_audit_log_exists_after_alias_deletion():
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
    )
    alias_id = alias.id
    emit_alias_audit_log(alias, AliasAuditLogAction.UpdateAlias, "")
    emit_alias_audit_log(alias, AliasAuditLogAction.UpdateAlias, "")
    delete_alias(alias, user, AliasDeleteReason.ManualAction, commit=True)

    db_alias = Alias.get_by(id=alias_id)
    assert db_alias is None

    logs_for_alias = AliasAuditLog.filter_by(alias_id=alias.id).all()
    assert len(logs_for_alias) == 4
    assert logs_for_alias[0].action == AliasAuditLogAction.CreateAlias.value
    assert logs_for_alias[1].action == AliasAuditLogAction.UpdateAlias.value
    assert logs_for_alias[2].action == AliasAuditLogAction.UpdateAlias.value
    assert logs_for_alias[3].action == AliasAuditLogAction.DeleteAlias.value


def test_alias_audit_log_for_transfer():
    original_user = create_new_user()
    new_user = create_new_user()
    alias = Alias.create(
        user_id=original_user.id,
        email=random_email(),
        mailbox_id=original_user.default_mailbox_id,
    )
    transfer_alias(alias, new_user, [new_user.default_mailbox])

    logs_for_alias = AliasAuditLog.filter_by(alias_id=alias.id).all()
    assert len(logs_for_alias) == 3
    assert logs_for_alias[0].action == AliasAuditLogAction.CreateAlias.value
    assert logs_for_alias[1].action == AliasAuditLogAction.TransferredAlias.value
    assert logs_for_alias[1].user_id == original_user.id
    assert logs_for_alias[2].action == AliasAuditLogAction.AcceptTransferAlias.value
    assert logs_for_alias[2].user_id == new_user.id
