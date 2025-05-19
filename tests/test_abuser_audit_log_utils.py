from typing import List

from app.abuser_audit_log_utils import emit_abuser_audit_log, AbuserAuditLogAction
from app.models import AbuserAuditLog
from app.utils import random_string
from tests.utils import create_new_user


def test_emit_abuser_audit_log_for_random_data():
    user = create_new_user()

    message = random_string()
    action = AbuserAuditLogAction.MarkAbuser
    emit_abuser_audit_log(
        user_id=user.id,
        action=action,
        message=message,
        commit=True,
    )

    logs_for_user: List[AbuserAuditLog] = AbuserAuditLog.filter_by(
        user_id=user.id, action=action.value
    ).all()
    assert len(logs_for_user) == 1
    assert logs_for_user[0].user_id == user.id
    assert logs_for_user[0].action == action.value
    assert logs_for_user[0].message == message
