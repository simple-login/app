from app import config
from app.db import Session
from job_runner import get_jobs_to_run
from app.models import Job, JobState
import arrow


def test_get_jobs_to_run(flask_client):
    now = arrow.now()
    for job in Job.all():
        Job.delete(job.id)
    expected_jobs_to_run = [
        # Jobs in ready state
        Job.create(name="", payload=""),
        Job.create(name="", payload="", run_at=now),
        # Jobs in taken state
        Job.create(
            name="",
            payload="",
            state=JobState.taken.value,
            taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS + 10)),
        ),
        Job.create(
            name="",
            payload="",
            state=JobState.taken.value,
            taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS + 10)),
            attempts=config.JOB_MAX_ATTEMPTS - 1,
        ),
        Job.create(
            name="",
            payload="",
            state=JobState.taken.value,
            taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS + 10)),
            run_at=now,
        ),
    ]
    # Jobs not to run
    # Job to run in the future
    Job.create(name="", payload="", run_at=now.shift(hours=2))
    # Job in done state
    Job.create(name="", payload="", state=JobState.done.value)
    # Job taken but not enough time has passed
    Job.create(
        name="",
        payload="",
        state=JobState.taken.value,
        taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS - 10)),
    )
    # Job taken with enough time but out of run_at zone
    Job.create(
        name="",
        payload="",
        state=JobState.taken.value,
        taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS + 10)),
        run_at=now.shift(hours=3),
    )
    # Job out of attempts
    Job.create(
        name="",
        payload="",
        state=JobState.taken.value,
        taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS + 10)),
        attempts=config.JOB_MAX_ATTEMPTS + 1,
    ),
    Session.commit()
    jobs = get_jobs_to_run()
    assert len(jobs) == len(expected_jobs_to_run)
    job_ids = [job.id for job in jobs]
    for job in expected_jobs_to_run:
        assert job.id in job_ids
