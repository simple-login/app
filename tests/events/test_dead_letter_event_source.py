import arrow

from app.db import Session
from app.models import SyncEvent
from events.event_source import DeadLetterEventSource, _DEAD_LETTER_THRESHOLD_MINUTES


class EventCounter:
    def __init__(self):
        self.processed_events = 0

    def on_event(self, event: SyncEvent):
        self.processed_events += 1


def setup_function(func):
    Session.query(SyncEvent).delete()


def test_dead_letter_does_not_take_untaken_events():
    source = DeadLetterEventSource(1)
    counter = EventCounter()
    threshold_time = arrow.utcnow().shift(minutes=-(_DEAD_LETTER_THRESHOLD_MINUTES) + 1)
    SyncEvent.create(
        content="test".encode("utf-8"), created_at=threshold_time, flush=True
    )
    SyncEvent.create(
        content="test".encode("utf-8"), taken_time=threshold_time, flush=True
    )
    events_processed = source.execute_loop(on_event=counter.on_event)
    assert len(events_processed) == 0
    assert counter.processed_events == 0


def test_dead_letter_takes_untaken_events_created_older_than_threshold():
    source = DeadLetterEventSource(1)
    counter = EventCounter()
    old_create = arrow.utcnow().shift(minutes=-_DEAD_LETTER_THRESHOLD_MINUTES - 1)
    SyncEvent.create(content="test".encode("utf-8"), created_at=old_create, flush=True)
    events_processed = source.execute_loop(on_event=counter.on_event)
    assert len(events_processed) == 1
    assert counter.processed_events == 1


def test_dead_letter_takes_taken_events_created_older_than_threshold():
    source = DeadLetterEventSource(1)
    counter = EventCounter()
    old_taken = arrow.utcnow().shift(minutes=-_DEAD_LETTER_THRESHOLD_MINUTES - 1)
    SyncEvent.create(content="test".encode("utf-8"), taken_time=old_taken, flush=True)
    events_processed = source.execute_loop(on_event=counter.on_event)
    assert len(events_processed) == 1
    assert counter.processed_events == 1
