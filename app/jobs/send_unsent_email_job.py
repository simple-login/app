from __future__ import annotations

import os
from io import BytesIO
from typing import Optional

import arrow
from sqlalchemy.orm import sessionmaker

from app import config, metrics, s3
from app.constants import JobType
from app.db import Session, engine
from app.log import LOG
from app.mail_sender import SendRequest, mail_sender
from app.models import Job, JobPriority


def backoff_secs(attempt: int) -> int:
    return config.UNSENT_EMAIL_BACKOFF_BASE_SECS * 2**attempt


class SendUnsentEmailJob:
    """Resend a SendRequest stored in S3, retrying with exponential backoff.

    The backoff is driven here rather than by the job runner's own retries:
    every failed attempt enqueues a fresh job for the next attempt.
    """

    def __init__(self, s3_key: str, attempt: int):
        self._s3_key = s3_key
        self._attempt = attempt

    def run(self) -> None:
        raw = s3.download_from_s3(self._s3_key) if s3.exists(self._s3_key) else None
        if raw is None:
            LOG.w(f"Unsent email {self._s3_key} no longer exists, skipping")
            return
        send_request = SendRequest.load_from_bytes(raw)
        send_request.ignore_smtp_errors = True
        if mail_sender.send(send_request, 2):
            s3.delete(self._s3_key)
            metrics.record_event("DeliverUnsentEmail", {"delivered": "true"})
            return
        metrics.record_event("DeliverUnsentEmail", {"delivered": "false"})
        if self._attempt < config.UNSENT_EMAIL_MAX_ATTEMPTS:
            SendUnsentEmailJob(self._s3_key, self._attempt + 1).store_job_in_db()
            return
        self._move_to_failed(raw)

    def _move_to_failed(self, raw: bytes) -> None:
        failed_key = (
            f"{config.UNSENT_EMAIL_S3_PREFIX}failed/{os.path.basename(self._s3_key)}"
        )
        s3.upload_raw(failed_key, BytesIO(raw))
        s3.delete(self._s3_key)
        LOG.e(
            f"Giving up on unsent email {self._s3_key} after {self._attempt} attempts, moved to {failed_key}"
        )
        metrics.record_event("DeliverUnsentEmailGaveUp", {"attempts": self._attempt})

    @staticmethod
    def create_from_job(job: Job) -> Optional[SendUnsentEmailJob]:
        return SendUnsentEmailJob(job.payload["s3_key"], job.payload["attempt"])

    def _build_job(self) -> Job:
        return Job(
            name=JobType.SEND_UNSENT_EMAIL.value,
            payload={"s3_key": self._s3_key, "attempt": self._attempt},
            priority=JobPriority.Default,
            run_at=arrow.now().shift(seconds=backoff_secs(self._attempt)),
        )

    def store_job_in_db(self) -> Job:
        job = self._build_job()
        Session.add(job)
        Session.commit()
        return job

    def store_job_in_independent_session(self) -> None:
        """Insert the job in its own transaction.

        Callers like the email handler send mail in the middle of a transaction
        that may later roll back; the job must outlive that.
        """
        session = sessionmaker(bind=engine)()
        try:
            session.add(self._build_job())
            session.commit()
        finally:
            session.close()
