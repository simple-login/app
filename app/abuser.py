from typing import Optional

from app.abuser_audit_log_utils import emit_abuser_audit_log, AbuserAuditLogAction
from app.db import Session
from app.jobs.mark_abuser_job import MarkAbuserJob
from app.models import User


def mark_user_as_abuser(
    abuse_user: User, note: str, admin_id: Optional[int] = None
) -> None:
    abuse_user.disabled = True

    emit_abuser_audit_log(
        user_id=abuse_user.id,
        action=AbuserAuditLogAction.MarkAbuser,
        message=note,
        admin_id=admin_id,
    )
    job = MarkAbuserJob(user=abuse_user)
    job.store_job_in_db()
    Session.commit()
