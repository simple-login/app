from io import BytesIO
from typing import List

import arrow
import pytest

from app import config, s3
from app.constants import JobType
from app.jobs.send_unsent_email_job import SendUnsentEmailJob
from app.mail_sender import mail_sender
from app.models import Job
from job_runner import process_job
from tests.test_mail_sender import closed_dummy_server, create_dummy_send_request

KEY = "unsent/test-send-unsent-email-job.sendrequest"
FAILED_KEY = "unsent/failed/test-send-unsent-email-job.sendrequest"


@pytest.fixture
def stored_request():
    s3.upload_raw(KEY, BytesIO(create_dummy_send_request().to_bytes()))
    yield KEY
    for key in (KEY, FAILED_KEY):
        if s3.exists(key):
            s3.delete(key)


@pytest.fixture
def smtp_down():
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{closed_dummy_server()}"]
    config.NOT_SEND_EMAIL = False
    yield
    config.POSTFIX_SERVERS = original_postfix_server
    config.NOT_SEND_EMAIL = True


def unsent_email_jobs() -> List[Job]:
    return Job.filter_by(name=JobType.SEND_UNSENT_EMAIL.value).all()


@mail_sender.store_emails_test_decorator
def test_success_resends_and_deletes_object(flask_client, stored_request):
    SendUnsentEmailJob(stored_request, 1).run()

    sent = mail_sender.get_stored_emails()
    assert len(sent) == 1
    assert sent[0].ignore_smtp_errors
    assert not s3.exists(stored_request)
    assert unsent_email_jobs() == []


def test_failure_enqueues_next_attempt_with_doubled_delay(
    flask_client, stored_request, smtp_down
):
    before = arrow.now()
    SendUnsentEmailJob(stored_request, 1).run()
    after = arrow.now()

    assert s3.exists(stored_request)
    jobs = unsent_email_jobs()
    assert len(jobs) == 1
    assert jobs[0].payload == {"s3_key": stored_request, "attempt": 2}
    delay = config.UNSENT_EMAIL_BACKOFF_BASE_SECS * 4
    assert before.shift(seconds=delay) <= jobs[0].run_at <= after.shift(seconds=delay)


def test_last_attempt_moves_object_to_failed(flask_client, stored_request, smtp_down):
    SendUnsentEmailJob(stored_request, config.UNSENT_EMAIL_MAX_ATTEMPTS).run()

    assert not s3.exists(stored_request)
    assert s3.exists(FAILED_KEY)
    assert unsent_email_jobs() == []


def test_missing_object_is_a_noop(flask_client):
    SendUnsentEmailJob("unsent/does-not-exist.sendrequest", 1).run()

    assert unsent_email_jobs() == []


@mail_sender.store_emails_test_decorator
def test_job_runner_dispatches_job(flask_client, stored_request):
    job = Job.create(
        name=JobType.SEND_UNSENT_EMAIL.value,
        payload={"s3_key": stored_request, "attempt": 1},
        run_at=arrow.now(),
        flush=True,
    )

    process_job(job)

    assert len(mail_sender.get_stored_emails()) == 1
    assert not s3.exists(stored_request)
