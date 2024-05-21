from app.events.event_dispatcher import EventDispatcher, Dispatcher
from app.events.generated.event_pb2 import EventContent, UserDeleted
from app.models import PartnerUser, User
from app.proton.utils import get_proton_partner
from tests.utils import create_new_user, random_token
from typing import Tuple


class OnMemoryDispatcher(Dispatcher):
    def __init__(self):
        self.memory = []

    def send(self, event: bytes):
        self.memory.append(event)


def _create_unlinked_user() -> User:
    return create_new_user()


def _create_linked_user() -> Tuple[User, PartnerUser]:
    user = _create_unlinked_user()
    partner_user = PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )

    return user, partner_user


def test_event_dispatcher_stores_events():
    dispatcher = OnMemoryDispatcher()

    (user, partner) = _create_linked_user()
    content = EventContent(user_deleted=UserDeleted())
    EventDispatcher.send_event(user, content, dispatcher, skip_if_webhook_missing=False)
    assert len(dispatcher.memory) == 1

    content = EventContent(user_deleted=UserDeleted())
    EventDispatcher.send_event(user, content, dispatcher, skip_if_webhook_missing=False)
    assert len(dispatcher.memory) == 2


def test_event_dispatcher_does_not_send_event_if_user_not_linked():
    dispatcher = OnMemoryDispatcher()

    user = _create_unlinked_user()
    content = EventContent(user_deleted=UserDeleted())
    EventDispatcher.send_event(user, content, dispatcher, skip_if_webhook_missing=False)
    assert len(dispatcher.memory) == 0

    content = EventContent(user_deleted=UserDeleted())
    EventDispatcher.send_event(user, content, dispatcher, skip_if_webhook_missing=False)
    assert len(dispatcher.memory) == 0
