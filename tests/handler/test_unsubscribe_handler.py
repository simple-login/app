from email.message import Message
from random import random
from typing import Iterable

from aiosmtpd.smtp import Envelope
from flask import url_for

from app.db import Session
from app.email import headers, status
from app.email_utils import parse_full_address
from app.handler.unsubscribe_handler import (
    UnsubscribeAction,
    UnsubscribeData,
    UnsubscribeEncoder,
    UnsubscribeHandler,
)
from app.mail_sender import mail_sender
from app.models import Alias, Contact, User
from tests.utils import create_new_user, login


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


def test_unsub_email_new_subject() -> Iterable:
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
    message[headers.SUBJECT] = UnsubscribeEncoder.encode(
        UnsubscribeData(UnsubscribeAction.DisableAlias, alias.id)
    )
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not Alias.get(alias.id).enabled
    assert 1 == len(mail_sender.get_stored_emails())
    # Disable contact
    message = Message()
    message[headers.SUBJECT] = UnsubscribeEncoder.encode(
        UnsubscribeData(UnsubscribeAction.DisableContact, contact.id)
    )
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert Contact.get(contact.id).block_forward
    assert 1 == len(mail_sender.get_stored_emails())
    # Disable newsletter
    message = Message()
    message[headers.SUBJECT] = UnsubscribeEncoder.encode(
        UnsubscribeData(UnsubscribeAction.UnsubscribeNewsletter, user.id)
    )
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not User.get(user.id).notification
    assert 1 == len(mail_sender.get_stored_emails())
    # Original mailto
    message = Message()
    original_recipient = f"{random()}@out.com"
    original_subject = f"Unsubsomehow{random()}"
    message[headers.SUBJECT] = UnsubscribeEncoder.encode(
        UnsubscribeData(
            UnsubscribeAction.OriginalUnsubscribeMailto,
            [alias.id, original_recipient, original_subject],
        )
    )
    mail_sender.purge_stored_emails()
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    assert mail_sent.envelope_to == original_recipient
    name, address = parse_full_address(mail_sent.msg[headers.FROM])
    assert alias.email == name
    assert alias.email == address
    assert mail_sent.msg[headers.TO] == original_recipient
    assert mail_sent.msg[headers.SUBJECT] == original_subject


def test_unsub_email_request(flask_client) -> Iterable:
    mail_sender.store_emails_instead_of_sending()
    user = login(flask_client)
    Session.commit()
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
    # Disable alias
    mail_sender.purge_stored_emails()
    req_data = UnsubscribeEncoder.encode(
        UnsubscribeData(UnsubscribeAction.DisableAlias, alias.id)
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert not Alias.get(alias.id).enabled
    assert 1 == len(mail_sender.get_stored_emails())
    # Disable contact
    mail_sender.purge_stored_emails()
    req_data = UnsubscribeEncoder.encode(
        UnsubscribeData(UnsubscribeAction.DisableContact, contact.id)
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert Contact.get(contact.id).block_forward
    assert 1 == len(mail_sender.get_stored_emails())
    # Disable newsletter
    mail_sender.purge_stored_emails()
    req_data = UnsubscribeEncoder.encode(
        UnsubscribeData(UnsubscribeAction.UnsubscribeNewsletter, user.id)
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert not User.get(user.id).notification
    assert 1 == len(mail_sender.get_stored_emails())
    # Original mailto
    original_recipient = f"{random()}@out.com"
    original_subject = f"Unsubsomehow{random()}"
    mail_sender.purge_stored_emails()
    req_data = UnsubscribeEncoder.encode(
        UnsubscribeData(
            UnsubscribeAction.OriginalUnsubscribeMailto,
            [alias.id, original_recipient, original_subject],
        )
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    assert mail_sent.envelope_to == original_recipient
    name, address = parse_full_address(mail_sent.msg[headers.FROM])
    assert alias.email == name
    assert alias.email == address
    assert mail_sent.msg[headers.TO] == original_recipient
    assert mail_sent.msg[headers.SUBJECT] == original_subject
