from typing import List

from app import config, mailbox_utils
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.models import UserAuditLog
from app.utils import random_string
from tests.utils import create_new_user, random_email


def setup_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = True


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False


def test_emit_alias_audit_log_for_random_data():
    user = create_new_user()

    message = random_string()
    action = UserAuditLogAction.CreateMailbox
    emit_user_audit_log(
        user=user,
        action=action,
        message=message,
        commit=True,
    )

    logs_for_user: List[UserAuditLog] = UserAuditLog.filter_by(
        user_id=user.id, action=action.value
    ).all()
    assert len(logs_for_user) == 1
    assert logs_for_user[0].user_id == user.id
    assert logs_for_user[0].user_email == user.email
    assert logs_for_user[0].action == action.value
    assert logs_for_user[0].message == message


def test_emit_audit_log_on_mailbox_creation():
    user = create_new_user()
    output = mailbox_utils.create_mailbox(
        user=user, email=random_email(), verified=True
    )

    logs_for_user: List[UserAuditLog] = UserAuditLog.filter_by(
        user_id=user.id,
        action=UserAuditLogAction.CreateMailbox.value,
    ).all()
    assert len(logs_for_user) == 1
    assert logs_for_user[0].user_id == user.id
    assert logs_for_user[0].user_email == user.email
    assert logs_for_user[0].action == UserAuditLogAction.CreateMailbox.value
    assert (
        logs_for_user[0].message
        == f"Create mailbox {output.mailbox.id} ({output.mailbox.email}). Verified=True"
    )
