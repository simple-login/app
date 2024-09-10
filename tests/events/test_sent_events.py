from app import config, alias_utils
from app.db import Session
from app.events.event_dispatcher import GlobalDispatcher
from app.events.generated import event_pb2
from app.models import Alias, User, PartnerUser
from tests.utils import random_token
from .event_test_utils import (
    OnMemoryDispatcher,
    _create_linked_user,
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


def _get_event_from_string(
    data: str, user: User, pu: PartnerUser
) -> event_pb2.EventContent:
    event = event_pb2.Event()
    event.ParseFromString(data)
    assert user.id == event.user_id
    assert pu.external_user_id == event.external_user_id
    assert pu.partner_id == event.partner_id
    return event.content


def test_fire_event_on_alias_creation():
    (user, pu) = _create_linked_user()
    alias = Alias.create_new_random(user)
    Session.flush()
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_created is not None
    alias_created = event_content.alias_created
    assert alias.id == alias_created.alias_id
    assert alias.email == alias_created.alias_email
    assert "" == alias_created.alias_note
    assert alias.enabled == alias_created.enabled


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
    assert alias.id == alias_created.alias_id
    assert alias.email == alias_created.alias_email
    assert note == alias_created.alias_note
    assert alias.enabled == alias_created.enabled


def test_fire_event_on_alias_deletion():
    (user, pu) = _create_linked_user()
    alias = Alias.create_new_random(user)
    alias_id = alias.id
    Session.flush()
    on_memory_dispatcher.clear()
    alias_utils.delete_alias(alias, user)
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_deleted is not None
    alias_deleted = event_content.alias_deleted
    assert alias_id == alias_deleted.alias_id
    assert alias.email == alias_deleted.alias_email


def test_fire_event_on_alias_status_change():
    (user, pu) = _create_linked_user()
    alias = Alias.create_new_random(user)
    Session.flush()
    on_memory_dispatcher.clear()
    alias_utils.change_alias_status(alias, True)
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.alias_status_change is not None
    event = event_content.alias_status_change
    assert alias.id == event.alias_id
    assert alias.email == event.alias_email
    assert event.enabled
