import app.alias_utils
from app import config
from app.db import Session
from app.events.event_dispatcher import GlobalDispatcher
from app.models import (
    Alias,
    Mailbox,
    AliasMailbox,
)
from tests.events.event_test_utils import (
    OnMemoryDispatcher,
    _get_event_from_string,
    _create_linked_user,
)
from tests.utils import login

on_memory_dispatcher = OnMemoryDispatcher()


def setup_module():
    GlobalDispatcher.set_dispatcher(on_memory_dispatcher)
    config.EVENT_WEBHOOK = "http://test"


def teardown_module():
    GlobalDispatcher.set_dispatcher(None)
    config.EVENT_WEBHOOK = None


def test_alias_transfer(flask_client):
    (source_user, source_user_pu) = _create_linked_user()
    source_user = login(flask_client, source_user)
    mb = Mailbox.create(user_id=source_user.id, email="mb@gmail.com", commit=True)

    alias = Alias.create_new_random(source_user)
    Session.commit()

    AliasMailbox.create(alias_id=alias.id, mailbox_id=mb.id, commit=True)

    (target_user, target_user_pu) = _create_linked_user()

    Mailbox.create(
        user_id=target_user.id, email="hey2@example.com", verified=True, commit=True
    )

    on_memory_dispatcher.clear()
    app.alias_utils.transfer_alias(alias, target_user, target_user.mailboxes())

    # refresh from db
    alias = Alias.get(alias.id)
    assert alias.user == target_user
    assert set(alias.mailboxes) == set(target_user.mailboxes())
    assert len(alias.mailboxes) == 2

    # Check events
    assert len(on_memory_dispatcher.memory) == 2
    # 1st delete event
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, source_user, source_user_pu)
    assert event_content.alias_deleted is not None
    alias_deleted = event_content.alias_deleted
    assert alias_deleted.id == alias.id
    assert alias_deleted.email == alias.email
    # 2nd create event
    event_data = on_memory_dispatcher.memory[1]
    event_content = _get_event_from_string(event_data, target_user, target_user_pu)
    assert event_content.alias_created is not None
    alias_created = event_content.alias_created
    assert alias.id == alias_created.id
    assert alias.email == alias_created.email
    assert alias.note or "" == alias_created.note
    assert alias.enabled == alias_created.enabled
