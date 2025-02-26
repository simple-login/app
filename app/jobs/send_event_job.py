from __future__ import annotations

import base64
from typing import Optional

import arrow

from app.constants import JobType
from app.errors import ProtonPartnerNotSetUp
from app.events.generated import event_pb2
from app.events.generated.event_pb2 import EventContent
from app.models import (
    User,
    Job,
    PartnerUser,
)
from app.proton.proton_partner import get_proton_partner
from events.event_sink import EventSink


class SendEventToWebhookJob:
    def __init__(self, user: User, event: EventContent):
        self._user: User = user
        self._event: EventContent = event

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
        event = event_pb2.Event(
            user_id=self._user.id,
            external_user_id=partner_user.external_user_id,
            partner_id=partner_user.partner_id,
            content=self._event,
        )

        serialized = event.SerializeToString()
        return sink.send_data_to_webhook(serialized)

    @staticmethod
    def create_from_job(job: Job) -> Optional[SendEventToWebhookJob]:
        user = User.get(job.payload["user_id"])
        if not user:
            return None
        event_data = base64.b64decode(job.payload["event"])
        event = event_pb2.EventContent()
        event.ParseFromString(event_data)

        return SendEventToWebhookJob(user=user, event=event)

    def store_job_in_db(self, run_at: Optional[arrow.Arrow]) -> Job:
        stub = self._event.SerializeToString()
        return Job.create(
            name=JobType.SEND_EVENT_TO_WEBHOOK.value,
            payload={
                "user_id": self._user.id,
                "event": base64.b64encode(stub).decode("utf-8"),
            },
            run_at=run_at if run_at is not None else arrow.now(),
            commit=True,
        )
