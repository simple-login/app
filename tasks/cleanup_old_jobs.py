import arrow
from sqlalchemy import or_, and_

from app import config
from app.db import Session
from app.log import LOG
from app.models import Job, JobState


def cleanup_old_jobs(oldest_allowed: arrow.Arrow):
    LOG.i(f"Deleting jobs older than {oldest_allowed}")
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
    Session.commit()
    LOG.i(f"Deleted {count} jobs")
