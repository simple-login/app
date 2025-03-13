from enum import Enum
from typing import Optional

from app.models import Alias, AliasAuditLog


class AliasAuditLogAction(Enum):
    CreateAlias = "create"
    ChangeAliasStatus = "change_status"
    DeleteAlias = "delete"
    UpdateAlias = "update"
    TrashAlias = "trash"

    InitiateTransferAlias = "initiate_transfer_alias"
    AcceptTransferAlias = "accept_transfer_alias"
    TransferredAlias = "transferred_alias"
    RestoreAlias = "restored_alias"

    ChangedMailboxes = "changed_mailboxes"

    CreateContact = "create_contact"
    UpdateContact = "update_contact"
    DeleteContact = "delete_contact"


def emit_alias_audit_log(
    alias: Alias,
    action: AliasAuditLogAction,
    message: str,
    user_id: Optional[int] = None,
    commit: bool = False,
):
    AliasAuditLog.create(
        user_id=user_id or alias.user_id,
        alias_id=alias.id,
        alias_email=alias.email,
        action=action.value,
        message=message,
        commit=commit,
    )
