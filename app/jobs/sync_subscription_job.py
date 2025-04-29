from __future__ import annotations

from typing import Optional

import arrow

from app.constants import JobType
from app.errors import ProtonPartnerNotSetUp
from app.events.generated import event_pb2
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.models import (
    User,
    Job,
    PartnerUser,
    JobPriority,
)
from app.proton.proton_partner import get_proton_partner
from events.event_sink import EventSink


class SyncSubscriptionJob:
    def __init__(self, user: User):
        self._user: User = user

    def run(self, sink: EventSink) -> bool:
        # Check if the current user has a partner_id
        try:
            proton_partner_id = get_proton_partner().id
        except ProtonPartnerNotSetUp:
            return False

        # It has. Retrieve the information for the PartnerUser
        partner_user = PartnerUser.get_by(
            user_id=self._user.id, partner_id=proton_partner_id
        )
        if partner_user is None:
            return True

        if self._user.lifetime:
            content = UserPlanChanged(lifetime=True)
        else:
            plan_end = self._user.get_active_subscription_end(
                include_partner_subscription=False
            )
            if plan_end:
                content = UserPlanChanged(plan_end_time=plan_end.timestamp)
            else:
                content = UserPlanChanged()

        event = event_pb2.Event(
            user_id=self._user.id,
            external_user_id=partner_user.external_user_id,
            partner_id=partner_user.partner_id,
            content=EventContent(user_plan_change=content),
        )

        serialized = event.SerializeToString()
        return sink.send_data_to_webhook(serialized)

    @staticmethod
    def create_from_job(job: Job) -> Optional[SyncSubscriptionJob]:
        user = User.get(job.payload["user_id"])
        if not user:
            return None

        return SyncSubscriptionJob(user=user)

    def store_job_in_db(
        self,
        run_at: Optional[arrow.Arrow],
        priority: JobPriority = JobPriority.Default,
        commit: bool = True,
    ) -> Job:
        return Job.create(
            name=JobType.SYNC_SUBSCRIPTION.value,
            payload={"user_id": self._user.id},
            priority=priority,
            run_at=run_at if run_at is not None else arrow.now(),
            commit=commit,
        )
