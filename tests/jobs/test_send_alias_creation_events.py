from app import config
from app.db import Session
from app.events.event_dispatcher import Dispatcher
from app.events.generated import event_pb2
from app.jobs.event_jobs import send_alias_creation_events_for_user
from app.models import Alias
from tests.utils import create_partner_linked_user


class MemStoreDispatcher(Dispatcher):
    def __init__(self):
        self.events = []

    def send(self, event: bytes):
        self.events.append(event)


def setup_module():
    config.EVENT_WEBHOOK = True


def teardown_module():
    config.EVENT_WEBHOOK = False


def test_send_alias_creation_events():
    [user, partner_user] = create_partner_linked_user()
    aliases = [Alias.create_new_random(user) for i in range(2)]
    Session.flush()
    dispatcher = MemStoreDispatcher()
    send_alias_creation_events_for_user(user, dispatcher=dispatcher, chunk_size=2)
    # 2 batches. 1st newsletter + first alias. 2nd last alias
    assert len(dispatcher.events) == 2
    decoded_event = event_pb2.Event.FromString(dispatcher.events[0])
    assert decoded_event.user_id == user.id
    assert decoded_event.external_user_id == partner_user.external_user_id
    event_list = decoded_event.content.alias_create_list.events
    assert len(event_list) == 2
    # 0 is newsletter alias
    assert event_list[1].id == aliases[0].id
    assert event_list[1].email == aliases[0].email
    assert event_list[1].note == ""
    assert event_list[1].enabled == aliases[0].enabled
    assert event_list[1].created_at == int(aliases[0].created_at.timestamp)
    decoded_event = event_pb2.Event.FromString(dispatcher.events[1])
    assert decoded_event.user_id == user.id
    assert decoded_event.external_user_id == partner_user.external_user_id
    event_list = decoded_event.content.alias_create_list.events
    assert len(event_list) == 1
    assert event_list[0].id == aliases[1].id
