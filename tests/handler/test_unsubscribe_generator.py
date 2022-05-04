from email.message import Message
from typing import Iterable

import pytest

from app import config
from app.db import Session
from app.email import headers
from app.handler.unsubscribe_generator import UnsubscribeGenerator
from app.models import Alias, Contact
from tests.utils import create_new_user


TEST_UNSUB_EMAIL = "unsub@sl.com"


def generate_sl_unsub_block_sender_data() -> Iterable:
    user = create_new_user()
    user.one_click_unsubscribe_block_sender = True
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
        f"<mailto:{TEST_UNSUB_EMAIL}?subject={contact.id}_>",
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
    generate_sl_unsub_block_sender_data(),
)
def test_sl_unsub_block_sender_data(
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


def generate_sl_unsub_not_block_sender_data() -> Iterable:
    user = create_new_user()
    user.one_click_unsubscribe_block_sender = False
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
        f"<mailto:{TEST_UNSUB_EMAIL}?subject={alias.id}=>",
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
        f"<{config.URL}/dashboard/encoded_unsubscribe?request={alias.id}>",
    )


@pytest.mark.parametrize(
    "alias_id, contact_id, unsub_via_mail, original_header, expected_header",
    generate_sl_unsub_block_sender_data(),
)
def test_sl_unsub_not_block_sender_data(
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
