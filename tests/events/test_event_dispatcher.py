from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserDeleted
from .event_test_utils import (
    _create_unlinked_user,
    OnMemoryDispatcher,
    _create_linked_user,
)


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
