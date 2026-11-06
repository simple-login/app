import arrow

from app.constants import JobType
from app.db import Session
from app.mail_sender import mail_sender
from app.models import Job, User, UserAuditLog
from app.user_audit_log_utils import (
    UserAuditLogAction,
    USER_REQUESTED_DELETION_REASON,
)
from job_runner import process_job
from tests.utils import create_new_user


def run_delete_account_job(payload: dict) -> None:
    job = Job.create(
        name=JobType.DELETE_ACCOUNT.value,
        payload=payload,
        run_at=arrow.now(),
        commit=True,
    )
    process_job(job)
    Session.commit()


@mail_sender.store_emails_test_decorator
def test_delete_account_job_emits_user_audit_log(flask_client):
    user = create_new_user()
    user_id = user.id
    user_email = user.email

    run_delete_account_job(
        {
            "user_id": user_id,
            "source": "webapp",
            "reason": USER_REQUESTED_DELETION_REASON,
        }
    )

    assert User.get(user_id) is None
    audit_log = UserAuditLog.get_by(
        user_id=user_id, action=UserAuditLogAction.DeleteUser.value
    )
    assert audit_log is not None
    assert audit_log.user_email == user_email
    assert (
        "Deleted by: delete-account job (marked for deletion from webapp)"
        in audit_log.message
    )
    assert f"Reason: {USER_REQUESTED_DELETION_REASON}" in audit_log.message


@mail_sender.store_emails_test_decorator
def test_delete_account_job_without_source_and_reason(flask_client):
    # Jobs created before the source and reason were stored in the payload
    user_id = create_new_user().id

    run_delete_account_job({"user_id": user_id})

    assert User.get(user_id) is None
    audit_log = UserAuditLog.get_by(
        user_id=user_id, action=UserAuditLogAction.DeleteUser.value
    )
    assert audit_log is not None
    assert (
        "Deleted by: delete-account job (marked for deletion from unknown)"
        in audit_log.message
    )
    assert "Reason: unknown" in audit_log.message
