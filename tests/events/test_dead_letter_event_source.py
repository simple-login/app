import arrow

from app.db import Session
from app.models import SyncEvent
from events import event_source
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
    assert events_processed[0].taken_time > old_create
    assert counter.processed_events == 1


def test_dead_letter_takes_taken_events_created_older_than_threshold():
    source = DeadLetterEventSource(1)
    counter = EventCounter()
    old_taken = arrow.utcnow().shift(minutes=-_DEAD_LETTER_THRESHOLD_MINUTES - 1)
    SyncEvent.create(content="test".encode("utf-8"), taken_time=old_taken, flush=True)
    events_processed = source.execute_loop(on_event=counter.on_event)
    assert len(events_processed) == 1
    assert events_processed[0].taken_time > old_taken
    assert counter.processed_events == 1


def _old_events(count: int) -> list[int]:
    old = arrow.utcnow().shift(minutes=-_DEAD_LETTER_THRESHOLD_MINUTES - 1)
    return [
        SyncEvent.create(content=b"test", created_at=old, flush=True).id
        for _ in range(count)
    ]


def test_dead_letter_processes_events_in_ascending_id():
    ids = _old_events(3)
    seen = []
    DeadLetterEventSource(1).execute_loop(on_event=lambda e: seen.append(e.id))
    assert seen == ids


def test_dead_letter_two_sources_get_different_events(monkeypatch):
    monkeypatch.setattr(event_source, "_DEAD_LETTER_BATCH_SIZE", 1)
    ids = _old_events(2)
    first = DeadLetterEventSource(1).execute_loop(on_event=lambda e: None)
    second = DeadLetterEventSource(1).execute_loop(on_event=lambda e: None)
    assert [e.id for e in first] == [ids[0]]
    assert [e.id for e in second] == [ids[1]]
