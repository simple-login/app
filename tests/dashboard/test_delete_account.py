from flask import url_for

from app.constants import JobType
from app.models import Job, UserAuditLog
from app.user_audit_log_utils import (
    UserAuditLogAction,
    USER_REQUESTED_DELETION_REASON,
)
from tests.utils import login, enter_sudo_mode


def test_delete_account_records_source_and_reason(flask_client):
    user = login(flask_client)
    enter_sudo_mode(flask_client, user)

    r = flask_client.post(
        url_for("dashboard.delete_account"),
        data={"form-name": "delete-account"},
    )

    assert r.status_code == 302
    audit_log = UserAuditLog.get_by(
        user_id=user.id, action=UserAuditLogAction.UserMarkedForDeletion.value
    )
    assert audit_log is not None
    assert "Source: webapp" in audit_log.message
    assert f"Reason: {USER_REQUESTED_DELETION_REASON}" in audit_log.message

    job = Job.filter_by(name=JobType.DELETE_ACCOUNT.value).order_by(Job.id.desc())[0]
    assert job.payload == {
        "user_id": user.id,
        "source": "webapp",
        "reason": USER_REQUESTED_DELETION_REASON,
    }
