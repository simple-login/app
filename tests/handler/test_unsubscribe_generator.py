from email.message import Message
from typing import Iterable

import pytest

from app import config
from app.db import Session
from app.email import headers
from app.handler.unsubscribe_encoder import (
    UnsubscribeAction,
    UnsubscribeEncoder,
    UnsubscribeOriginalData,
)
from app.handler.unsubscribe_generator import UnsubscribeGenerator
from app.models import Alias, Contact, UnsubscribeBehaviourEnum
from tests.utils import create_new_user


TEST_UNSUB_EMAIL = "unsub@sl.com"


def generate_unsub_block_contact_data() -> Iterable:
    user = create_new_user()
    user.unsub_behaviour = UnsubscribeBehaviourEnum.BlockContact
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )

    subject = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.DisableContact, contact.id
    )
    yield (
        alias.id,
        contact.id,
        True,
        "<https://lol.com>, <mailto:somewhere@not.net>",
        f"<mailto:{TEST_UNSUB_EMAIL}?subject={subject}>",
    )
    yield (
        alias.id,
        contact.id,
        False,
        "<https://lol.com>, <mailto:somewhere@not.net>",
        f"<{config.URL}/dashboard/block_contact/{contact.id}>",
    )
    yield (
        alias.id,
        contact.id,
        False,
        None,
        f"<{config.URL}/dashboard/block_contact/{contact.id}>",
    )


@pytest.mark.parametrize(
    "alias_id, contact_id, unsub_via_mail, original_header, expected_header",
    generate_unsub_block_contact_data(),
)
def test_unsub_disable_contact(
    alias_id, contact_id, unsub_via_mail, original_header, expected_header
):
    alias = Alias.get(alias_id)
    contact = Contact.get(contact_id)
    config.UNSUBSCRIBER = TEST_UNSUB_EMAIL if unsub_via_mail else None
    message = Message()
    message[headers.LIST_UNSUBSCRIBE] = original_header
    message = UnsubscribeGenerator().add_header_to_message(alias, contact, message)
    assert expected_header == message[headers.LIST_UNSUBSCRIBE]
    if not expected_header or expected_header.find("<http") == -1:
        assert message[headers.LIST_UNSUBSCRIBE_POST] is None
    else:
        assert "List-Unsubscribe=One-Click" == message[headers.LIST_UNSUBSCRIBE_POST]


def generate_unsub_disable_alias_data() -> Iterable:
    user = create_new_user()
    user.unsub_behaviour = UnsubscribeBehaviourEnum.DisableAlias
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )

    subject = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.DisableAlias, alias.id
    )
    yield (
        alias.id,
        contact.id,
        True,
        "<https://lol.com>, <mailto:somewhere@not.net>",
        f"<mailto:{TEST_UNSUB_EMAIL}?subject={subject}>",
    )
    yield (
        alias.id,
        contact.id,
        False,
        "<https://lol.com>, <mailto:somewhere@not.net>",
        f"<{config.URL}/dashboard/unsubscribe/{alias.id}>",
    )
    yield (
        alias.id,
        contact.id,
        False,
        None,
        f"<{config.URL}/dashboard/unsubscribe/{alias.id}>",
    )


@pytest.mark.parametrize(
    "alias_id, contact_id, unsub_via_mail, original_header, expected_header",
    generate_unsub_disable_alias_data(),
)
def test_unsub_disable_alias(
    alias_id, contact_id, unsub_via_mail, original_header, expected_header
):
    alias = Alias.get(alias_id)
    contact = Contact.get(contact_id)
    config.UNSUBSCRIBER = TEST_UNSUB_EMAIL if unsub_via_mail else None
    message = Message()
    message[headers.LIST_UNSUBSCRIBE] = original_header
    message = UnsubscribeGenerator().add_header_to_message(alias, contact, message)
    assert expected_header == message[headers.LIST_UNSUBSCRIBE]
    if not expected_header or expected_header.find("<http") == -1:
        assert message[headers.LIST_UNSUBSCRIBE_POST] is None
    else:
        assert "List-Unsubscribe=One-Click" == message[headers.LIST_UNSUBSCRIBE_POST]


def generate_unsub_preserve_original_data() -> Iterable:
    user = create_new_user()
    user.unsub_behaviour = UnsubscribeBehaviourEnum.PreserveOriginal
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
        commit=True,
    )

    yield (
        alias.id,
        contact.id,
        True,
        "<https://lol.com>, <mailto:somewhere@not.net>",
        "<https://lol.com>",
    )
    yield (
        alias.id,
        contact.id,
        False,
        "<https://lol.com>, <mailto:somewhere@not.net>",
        "<https://lol.com>",
    )
    unsub_data = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.OriginalUnsubscribeMailto,
        UnsubscribeOriginalData(alias.id, "test@test.com", "hello"),
    )
    yield (
        alias.id,
        contact.id,
        True,
        "<mailto:test@test.com?subject=hello>",
        f"<mailto:{TEST_UNSUB_EMAIL}?subject={unsub_data}>",
    )
    yield (
        alias.id,
        contact.id,
        False,
        "<mailto:test@test.com?subject=hello>",
        f"<{config.URL}/dashboard/unsubscribe/encoded?data={unsub_data}>",
    )
    yield (alias.id, contact.id, True, None, None)
    yield (alias.id, contact.id, False, None, None)


@pytest.mark.parametrize(
    "alias_id, contact_id, unsub_via_mail, original_header, expected_header",
    generate_unsub_preserve_original_data(),
)
def test_unsub_preserve_original(
    alias_id, contact_id, unsub_via_mail, original_header, expected_header
):
    alias = Alias.get(alias_id)
    contact = Contact.get(contact_id)
    config.UNSUBSCRIBER = TEST_UNSUB_EMAIL if unsub_via_mail else None
    message = Message()
    message[headers.LIST_UNSUBSCRIBE] = original_header
    message = UnsubscribeGenerator().add_header_to_message(alias, contact, message)
    assert expected_header == message[headers.LIST_UNSUBSCRIBE]
    if not expected_header or expected_header.find("<http") == -1:
        assert message[headers.LIST_UNSUBSCRIBE_POST] is None
    else:
        assert "List-Unsubscribe=One-Click" == message[headers.LIST_UNSUBSCRIBE_POST]
