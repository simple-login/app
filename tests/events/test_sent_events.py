import arrow

from app import config, alias_utils, alias_delete
from app.db import Session
from app.events.event_dispatcher import GlobalDispatcher
from app.models import Alias, SyncEvent
from tests.utils import random_token
from .event_test_utils import (
    OnMemoryDispatcher,
    _create_linked_user,
    _get_event_from_string,
)

on_memory_dispatcher = OnMemoryDispatcher()


def setup_module():
    GlobalDispatcher.set_dispatcher(on_memory_dispatcher)
    config.EVENT_WEBHOOK = "http://test"


def teardown_module():
    GlobalDispatcher.set_dispatcher(None)
    config.EVENT_WEBHOOK = None


def setup_function(func):
    on_memory_dispatcher.clear()


def test_event_taken_updates():
    event = SyncEvent.create(content="test".encode("utf-8"), flush=True)
    assert event.taken_time is None
    assert event.mark_as_taken()
    assert event.taken_time is not None


def test_event_mark_as_taken_does_nothing_for_taken_events():
    now = arrow.utcnow()
    event = SyncEvent.create(content="test".encode("utf-8"), taken_time=now, flush=True)
    assert not event.mark_as_taken()


def test_event_mark_as_taken_does_nothing_for_not_before_events():
    now = arrow.utcnow()
    event = SyncEvent.create(content="test".encode("utf-8"), taken_time=now, flush=True)
    older_than = now.shift(minutes=-1)
    assert not event.mark_as_taken(allow_taken_older_than=older_than)


def test_event_mark_as_taken_works_for_before_events():
    now = arrow.utcnow()
    event = SyncEvent.create(content="test".encode("utf-8"), taken_time=now, flush=True)
    older_than = now.shift(minutes=+1)
    assert event.mark_as_taken(allow_taken_older_than=older_than)


def test_fire_event_on_alias_creation():
    (user, pu) = _create_linked_user()
    alias = Alias.create_new_random(user)
    Session.flush()
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_created is not None
    alias_created = event_content.alias_created
    assert alias.id == alias_created.id
    assert alias.email == alias_created.email
    assert "" == alias_created.note
    assert alias.enabled == alias_created.enabled
    assert int(alias.created_at.timestamp) == alias_created.created_at


def test_fire_event_on_alias_creation_with_note():
    (user, pu) = _create_linked_user()
    note = random_token(10)
    alias = Alias.create_new_random(user, note=note)
    Session.flush()
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_created is not None
    alias_created = event_content.alias_created
    assert alias.id == alias_created.id
    assert alias.email == alias_created.email
    assert note == alias_created.note
    assert alias.enabled == alias_created.enabled


def test_fire_event_on_alias_deletion():
    (user, pu) = _create_linked_user()
    alias = Alias.create_new_random(user)
    alias_id = alias.id
    Session.flush()
    on_memory_dispatcher.clear()
    alias_delete.delete_alias(alias, user)
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_deleted is not None
    alias_deleted = event_content.alias_deleted
    assert alias_id == alias_deleted.id
    assert alias.email == alias_deleted.email


def test_fire_event_on_alias_status_change():
    (user, pu) = _create_linked_user()
    alias = Alias.create_new_random(user)
    Session.flush()
    on_memory_dispatcher.clear()
    alias_utils.change_alias_status(alias, enabled=True)
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_status_change is not None
    event = event_content.alias_status_change
    assert alias.id == event.id
    assert alias.email == event.email
    assert int(alias.created_at.timestamp) == event.created_at
    assert event.enabled
