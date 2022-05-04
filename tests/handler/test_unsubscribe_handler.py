from email.message import Message
from random import random
from typing import Iterable

from aiosmtpd.smtp import Envelope

from app.db import Session
from app.email import headers, status
from app.handler.unsubscribe_handler import (
    UnsubscribeHandler,
)
from app.mail_sender import mail_sender
from app.models import Alias, Contact, User
from tests.utils import create_new_user


def test_unsub_email_old_subject() -> Iterable:
    mail_sender.store_emails_instead_of_sending()
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email=f"{random()}@sl.local",
        block_forward=False,
        commit=True,
    )
    envelope = Envelope()
    envelope.mail_from = user.email
    # Disable alias
    message = Message()
    message[headers.SUBJECT] = f"{alias.id}="
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not Alias.get(alias.id).enabled
    assert 1 == len(mail_sender.get_stored_emails())
    # Disable contact
    message = Message()
    message[headers.SUBJECT] = f"{contact.id}_"
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert Contact.get(contact.id).block_forward
    assert 1 == len(mail_sender.get_stored_emails())
    # Disable newsletter
    message = Message()
    message[headers.SUBJECT] = f"{user.id}*"
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not User.get(user.id).notification
    assert 1 == len(mail_sender.get_stored_emails())
