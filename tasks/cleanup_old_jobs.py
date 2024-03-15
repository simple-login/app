import arrow
from sqlalchemy import or_, and_

from app import config
from app.log import LOG
from app.models import Job, JobState


def cleanup_old_jobs():
    count = Job.filter(
        or_(
            Job.state == JobState.done,
            Job.state == JobState.error,
            and_(Job.state == JobState.taken, Job.attempts >= config.JOB_MAX_ATTEMPTS),
        ),
        Job.updated_at < arrow.now().shift(days=-15),
    ).delete()
    LOG.i(f"Deleted {count} jobs")
