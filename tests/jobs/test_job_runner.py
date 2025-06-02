from app import config
from app.db import Session
from job_runner import get_jobs_to_run
from app.models import Job, JobPriority, JobState
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
    )
    # Job marked as error
    Job.create(
        name="",
        payload="",
        state=JobState.error.value,
        taken_at=now.shift(minutes=-(config.JOB_TAKEN_RETRY_WAIT_MINS + 10)),
        attempts=config.JOB_MAX_ATTEMPTS + 1,
    )

    Session.commit()
    taken_before_time = arrow.now().shift(minutes=-config.JOB_TAKEN_RETRY_WAIT_MINS)
    jobs = get_jobs_to_run(taken_before_time)
    assert len(jobs) == len(expected_jobs_to_run)
    job_ids = [job.id for job in jobs]
    for job in expected_jobs_to_run:
        assert job.id in job_ids


def test_get_jobs_to_run_respects_priority(flask_client):
    now = arrow.now()
    for job in Job.all():
        Job.delete(job.id)

    j1 = Job.create(
        name="", payload="", run_at=now.shift(minutes=-1), priority=JobPriority.High
    )
    j2 = Job.create(
        name="", payload="", run_at=now.shift(minutes=-2), priority=JobPriority.Default
    )
    j3 = Job.create(
        name="", payload="", run_at=now.shift(minutes=-3), priority=JobPriority.Default
    )
    j4 = Job.create(
        name="", payload="", run_at=now.shift(minutes=-4), priority=JobPriority.Low
    )
    j5 = Job.create(
        name="", payload="", run_at=now.shift(minutes=-2), priority=JobPriority.High
    )

    Session.commit()
    taken_before_time = arrow.now().shift(minutes=-config.JOB_TAKEN_RETRY_WAIT_MINS)
    jobs = get_jobs_to_run(taken_before_time)
    assert len(jobs) == 5

    job_ids = [job.id for job in jobs]

    # The expected outcome is:
    # 1. j5 -> 2 mins ago and High
    # 2. j1 -> 1 min ago and High
    # --- The 2 above are high, so they should be the first ones. j5 is first as it's been pending for a longer time
    # 3. j3 -> 3 mins ago and Default
    # 4. j2 -> 2 mins ago and Default
    # --- The 2 above are both default, and again, are sorted by run_at ascendingly
    # 5. j4 -> 3 mins ago and Low. Even if it is the one that has been waiting the most, as it's Low, it's the last one
    assert job_ids == [j5.id, j1.id, j3.id, j2.id, j4.id]
