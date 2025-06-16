from typing import Optional

from app.abuser_audit_log_utils import emit_abuser_audit_log, AbuserAuditLogAction
from app.db import Session
from app.jobs.mark_abuser_job import MarkAbuserJob
from app.log import LOG
from app.models import User, AbuserData


def mark_user_as_abuser(
    abuse_user: User, note: str, admin_id: Optional[int] = None
) -> None:
    LOG.i(f"Marking user {abuse_user.id} as an abuser.")
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


def unmark_as_abusive_user(
    user_id: int, note: str, admin_id: Optional[int] = None
) -> None:
    """
    Fully remove abuser archive and lookup data for a given user_id.
    This reverses the effects of archive_abusive_user().
    """
    LOG.i(f"Unmarking user {user_id} as an abuser.")
    abuser_data_entry = AbuserData.filter_by(user_id=user_id).first()

    if abuser_data_entry:
        Session.delete(abuser_data_entry)

    user = User.get(user_id)
    user.disabled = False

    emit_abuser_audit_log(
        user_id=user.id,
        admin_id=admin_id,
        action=AbuserAuditLogAction.UnmarkAbuser,
        message=note,
    )
    Session.commit()
