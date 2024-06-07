from app import config
from app.db import Session
from app.events.event_dispatcher import Dispatcher
from app.jobs.event_jobs import send_alias_creation_events_for_user
from app.models import Alias
from tests.utils import create_new_user


class MemStoreDispatcher(Dispatcher):
    def __init__(self):
        self.events = []

    def send(self, event: bytes):
        self.events.apend(event)


def setup_module():
    config.EVENT_WEBHOOK = True


def teardown_module():
    config.EVENT_WEBHOOK = False


def test_send_alias_creation_events():
    user = create_new_user()
    aliases = [Alias.create_new_random(user) for i in range(2)]
    Session.commit()
    dispatcher = MemStoreDispatcher()
    send_alias_creation_events_for_user(user, dispatcher=dispatcher, chunk_size=2)
    assert len(dispatcher.events) == len(aliases)
