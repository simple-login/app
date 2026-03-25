from __future__ import annotations

from typing import Optional

import arrow

from app.abuser_utils import store_abuse_data
from app.constants import JobType
from app.models import (
    User,
    Job,
    JobPriority,
)


class MarkAbuserJob:
    def __init__(self, user: User):
        self._user: User = user

    def run(self) -> None:
        store_abuse_data(user=self._user)

    @staticmethod
    def create_from_job(job: Job) -> Optional[MarkAbuserJob]:
        user = User.get(job.payload["user_id"])
        if not user:
            return None

        return MarkAbuserJob(user)

    def store_job_in_db(self) -> Job:
        return Job.create(
            name=JobType.ABUSER_MARK.value,
            payload={"user_id": self._user.id},
            priority=JobPriority.Low,
            run_at=arrow.now(),
            commit=True,
        )
