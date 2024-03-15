import arrow
from sqlalchemy import or_, and_

from app import config
from app.log import LOG
from app.models import Job, JobState


def cleanup_old_jobs(oldest_allowed: arrow.Arrow):
    count = Job.filter(
        or_(
            Job.state == JobState.done.value,
            Job.state == JobState.error.value,
            and_(
                Job.state == JobState.taken.value,
                Job.attempts >= config.JOB_MAX_ATTEMPTS,
            ),
        ),
        Job.updated_at < oldest_allowed,
    ).delete()
    LOG.i(f"Deleted {count} jobs")
