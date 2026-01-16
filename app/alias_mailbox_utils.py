from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from app.alias_audit_log_utils import emit_alias_audit_log, AliasAuditLogAction
from app.db import Session
from app.models import Alias, AliasMailbox, Mailbox

_MAX_MAILBOXES_PER_ALIAS = 20


class CannotSetMailboxesForAliasCause(Enum):
    Forbidden = "Forbidden"
    EmptyMailboxes = "Must choose at least one mailbox"
    TooManyMailboxes = "Too many mailboxes"


@dataclass
class SetMailboxesForAliasResult:
    performed_change: bool
    reason: Optional[CannotSetMailboxesForAliasCause]


def set_mailboxes_for_alias(
    user_id: int, alias: Alias, mailbox_ids: List[int]
) -> Optional[CannotSetMailboxesForAliasCause]:
    if len(mailbox_ids) == 0:
        return CannotSetMailboxesForAliasCause.EmptyMailboxes
    if len(mailbox_ids) > _MAX_MAILBOXES_PER_ALIAS:
        return CannotSetMailboxesForAliasCause.TooManyMailboxes

    mailboxes = (
        Session.query(Mailbox)
        .filter(
            Mailbox.id.in_(mailbox_ids),
            Mailbox.user_id == user_id,
            Mailbox.verified == True,  # noqa: E712
        )
        .order_by(Mailbox.id.asc())
        .all()
    )
    if len(mailboxes) != len(mailbox_ids):
        return CannotSetMailboxesForAliasCause.Forbidden

    # Check for admin-disabled mailboxes
    for mailbox in mailboxes:
        if mailbox.is_admin_disabled():
            return CannotSetMailboxesForAliasCause.Forbidden

    # first remove all existing alias-mailboxes links
    AliasMailbox.filter_by(alias_id=alias.id).delete()
    Session.flush()

    # then add all new mailboxes, being the first the one associated with the alias
    for i, mailbox in enumerate(mailboxes):
        if i == 0:
            alias.mailbox_id = mailboxes[0].id
        else:
            AliasMailbox.create(alias_id=alias.id, mailbox_id=mailbox.id)

    emit_alias_audit_log(
        alias=alias,
        action=AliasAuditLogAction.ChangedMailboxes,
        message=",".join([f"{mailbox.id} ({mailbox.email})" for mailbox in mailboxes]),
    )

    return None
