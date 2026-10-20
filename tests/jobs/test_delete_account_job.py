import arrow

from app.constants import JobType
from app.db import Session
from app.mail_sender import mail_sender
from app.models import Job, User, UserAuditLog
from app.user_audit_log_utils import UserAuditLogAction
from job_runner import process_job
from tests.utils import create_new_user


@mail_sender.store_emails_test_decorator
def test_delete_account_job_emits_user_audit_log(flask_client):
    user = create_new_user()
    user_id = user.id
    user_email = user.email
    job = Job.create(
        name=JobType.DELETE_ACCOUNT.value,
        payload={"user_id": user_id},
        run_at=arrow.now(),
        commit=True,
    )

    process_job(job)
    Session.commit()

    assert User.get(user_id) is None
    audit_log = UserAuditLog.get_by(
        user_id=user_id, action=UserAuditLogAction.DeleteUser.value
    )
    assert audit_log is not None
    assert audit_log.user_email == user_email
