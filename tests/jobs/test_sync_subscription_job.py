import arrow
from typing import List

from app.constants import JobType
from app.events.generated import event_pb2
from app.jobs.sync_subscription_job import SyncSubscriptionJob
from app.models import PartnerUser, JobPriority, SyncEvent
from app.proton.proton_partner import get_proton_partner
from events.event_sink import EventSink
from tests.utils import create_new_user, random_token


class InMemorySink(EventSink):
    def __init__(self):
        self.events = []

    def process(self, event: SyncEvent) -> bool:
        raise RuntimeError("Should not be called")

    def send_data_to_webhook(self, data: bytes) -> bool:
        self.events.append(data)
        return True


def test_serialize_and_deserialize_job():
    user = create_new_user()
    run_at = arrow.now().shift(hours=10)
    priority = JobPriority.High
    db_job = SyncSubscriptionJob(user).store_job_in_db(run_at=run_at, priority=priority)
    assert db_job.run_at == run_at
    assert db_job.priority == priority
    assert db_job.name == JobType.SYNC_SUBSCRIPTION.value

    job = SyncSubscriptionJob.create_from_job(db_job)
    assert job._user.id == user.id


def _run_send_event_test(partner_user: PartnerUser) -> event_pb2.Event:
    job = SyncSubscriptionJob(partner_user.user)
    sink = InMemorySink()
    assert job.run(sink)

    sent_events: List[bytes] = sink.events
    assert len(sent_events) == 1

    decoded = event_pb2.Event()
    decoded.ParseFromString(sent_events[0])

    return decoded


def test_send_event_to_webhook_free():
    user = create_new_user()
    external_user_id = random_token(10)
    partner_user = PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        external_user_id=external_user_id,
        flush=True,
    )

    res = _run_send_event_test(partner_user)

    assert res.user_id == user.id
    assert res.partner_id == partner_user.partner_id
    assert res.external_user_id == external_user_id
    assert res.content == event_pb2.EventContent(
        user_plan_change=event_pb2.UserPlanChanged()
    )


def test_send_event_to_webhook_lifetime():
    user = create_new_user()
    user.lifetime = True
    external_user_id = random_token(10)
    partner_user = PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        external_user_id=external_user_id,
        commit=True,
    )

    res = _run_send_event_test(partner_user)

    assert res.user_id == user.id
    assert res.partner_id == partner_user.partner_id
    assert res.external_user_id == external_user_id
    assert res.content == event_pb2.EventContent(
        user_plan_change=event_pb2.UserPlanChanged(lifetime=True)
    )
