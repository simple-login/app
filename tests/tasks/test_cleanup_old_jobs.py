import arrow

from app import config
from app.models import Job, JobState
from tasks.cleanup_old_jobs import cleanup_old_jobs


def test_cleanup_old_jobs():
    Job.filter().delete()
    now = arrow.now()
    delete_ids = [
        Job.create(
            updated_at=now.shift(minutes=-1),
            state=JobState.done.value,
            name="",
            payload="",
            flush=True,
        ).id,
        Job.create(
            updated_at=now.shift(minutes=-1),
            state=JobState.error.value,
            name="",
            payload="",
            flush=True,
        ).id,
        Job.create(
            updated_at=now.shift(minutes=-1),
            state=JobState.taken.value,
            attempts=config.JOB_MAX_ATTEMPTS,
            name="",
            payload="",
            flush=True,
        ).id,
    ]

    keep_ids = [
        Job.create(
            updated_at=now.shift(minutes=+1),
            state=JobState.done.value,
            name="",
            payload="",
            flush=True,
        ).id,
        Job.create(
            updated_at=now.shift(minutes=+1),
            state=JobState.error.value,
            name="",
            payload="",
            flush=True,
        ).id,
        Job.create(
            updated_at=now.shift(minutes=+1),
            state=JobState.taken.value,
            attempts=config.JOB_MAX_ATTEMPTS,
            name="",
            payload="",
            flush=True,
        ).id,
        Job.create(
            updated_at=now.shift(minutes=-1),
            state=JobState.taken.value,
            attempts=config.JOB_MAX_ATTEMPTS - 1,
            name="",
            payload="",
            flush=True,
        ).id,
    ]
    cleanup_old_jobs(now)
    for delete_id in delete_ids:
        assert Job.get(id=delete_id) is None
    for keep_id in keep_ids:
        assert Job.get(id=keep_id) is not None
