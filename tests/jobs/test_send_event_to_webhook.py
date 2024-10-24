import arrow

from app import config
from app.events.generated.event_pb2 import EventContent, AliasDeleted
from app.jobs.send_event_job import SendEventToWebhookJob
from app.models import PartnerUser
from app.proton.utils import get_proton_partner
from events.event_sink import ConsoleEventSink
from tests.utils import create_new_user, random_token


def test_serialize_and_deserialize_job():
    user = create_new_user()
    alias_id = 34
    alias_email = "a@b.c"
    event = EventContent(alias_deleted=AliasDeleted(id=alias_id, email=alias_email))
    run_at = arrow.now().shift(hours=10)
    db_job = SendEventToWebhookJob(user, event).store_job_in_db(run_at=run_at)
    assert db_job.run_at == run_at
    assert db_job.name == config.JOB_SEND_EVENT_TO_WEBHOOK
    job = SendEventToWebhookJob.create_from_job(db_job)
    assert job._user.id == user.id
    assert job._event.alias_deleted.id == alias_id
    assert job._event.alias_deleted.email == alias_email


def test_send_event_to_webhook():
    user = create_new_user()
    PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        external_user_id=random_token(10),
        flush=True,
    )
    alias_id = 34
    alias_email = "a@b.c"
    event = EventContent(alias_deleted=AliasDeleted(id=alias_id, email=alias_email))
    job = SendEventToWebhookJob(user, event)
    sink = ConsoleEventSink()
    assert job.run(sink)
