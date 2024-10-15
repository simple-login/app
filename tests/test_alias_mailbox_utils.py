from typing import Tuple

from app.alias_audit_log_utils import AliasAuditLogAction
from app.alias_mailbox_utils import (
    set_mailboxes_for_alias,
    CannotSetMailboxesForAliasCause,
)
from app.models import Alias, Mailbox, User, AliasMailbox, AliasAuditLog
from tests.utils import create_new_user, random_email


def setup() -> Tuple[User, Alias]:
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    return user, alias


def test_set_mailboxes_for_alias_empty_list():
    user, alias = setup()
    err = set_mailboxes_for_alias(user.id, alias, [])
    assert err is CannotSetMailboxesForAliasCause.EmptyMailboxes


def test_set_mailboxes_for_alias_mailbox_for_other_user():
    user, alias = setup()
    another_user = create_new_user()
    err = set_mailboxes_for_alias(user.id, alias, [another_user.default_mailbox_id])
    assert err is CannotSetMailboxesForAliasCause.Forbidden


def test_set_mailboxes_for_alias_mailbox_not_exists():
    user, alias = setup()
    err = set_mailboxes_for_alias(user.id, alias, [9999999])
    assert err is CannotSetMailboxesForAliasCause.Forbidden


def test_set_mailboxes_for_alias_mailbox_success():
    user, alias = setup()
    mb1 = Mailbox.create(
        user_id=user.id,
        email=random_email(),
        verified=True,
    )
    mb2 = Mailbox.create(
        user_id=user.id,
        email=random_email(),
        verified=True,
        commit=True,
    )
    err = set_mailboxes_for_alias(user.id, alias, [mb1.id, mb2.id])
    assert err is None

    db_alias = Alias.get_by(id=alias.id)
    assert db_alias is not None
    assert db_alias.mailbox_id == mb1.id

    alias_mailboxes = AliasMailbox.filter_by(alias_id=alias.id).all()
    assert len(alias_mailboxes) == 1
    assert alias_mailboxes[0].mailbox_id == mb2.id

    audit_logs = AliasAuditLog.filter_by(alias_id=alias.id).all()
    assert len(audit_logs) == 2
    assert audit_logs[0].action == AliasAuditLogAction.CreateAlias.value
    assert audit_logs[1].action == AliasAuditLogAction.ChangedMailboxes.value
    assert audit_logs[1].message == f"{mb1.id},{mb2.id}"
