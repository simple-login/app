from email.message import Message
from random import random

from aiosmtpd.smtp import Envelope
from flask import url_for

from app.db import Session
from app.email import headers, status
from app.email_utils import parse_full_address
from app.handler.unsubscribe_encoder import (
    UnsubscribeEncoder,
    UnsubscribeAction,
    UnsubscribeOriginalData,
)
from app.handler.unsubscribe_handler import (
    UnsubscribeHandler,
)
from app.mail_sender import mail_sender
from app.models import Alias, Contact, User
from tests.utils import create_new_user, login


def _get_envelope_and_message(user: User, subject: str) -> (Envelope, Message):
    envelope = Envelope()
    envelope.mail_from = user.email
    message = Message()
    message[headers.SUBJECT] = subject
    return envelope, message


@mail_sender.store_emails_test_decorator
def test_old_subject_disable_alias():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    envelope, message = _get_envelope_and_message(user, f"{alias.id}=")
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not Alias.get(alias.id).enabled
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_old_subject_block_contact():
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
    envelope, message = _get_envelope_and_message(user, f"{contact.id}_")
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert Contact.get(contact.id).block_forward
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_old_subject_disable_newsletter():
    user = create_new_user()
    envelope, message = _get_envelope_and_message(user, f"{user.id}*")
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not User.get(user.id).notification
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_new_subject_disable_alias():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    header = UnsubscribeEncoder.encode_subject(UnsubscribeAction.DisableAlias, alias.id)
    envelope, message = _get_envelope_and_message(user, header)
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not Alias.get(alias.id).enabled
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_new_subject_block_contact():
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
    header = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.DisableContact, contact.id
    )
    envelope, message = _get_envelope_and_message(user, header)
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert Contact.get(contact.id).block_forward
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_new_subject_disable_newsletter():
    user = create_new_user()
    header = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.UnsubscribeNewsletter, user.id
    )
    envelope, message = _get_envelope_and_message(user, header)
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert not User.get(user.id).notification
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_new_subject_original_unsub():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    envelope = Envelope()
    envelope.mail_from = user.email
    message = Message()
    original_recipient = f"{random()}@out.com"
    original_subject = f"Unsubsomehow{random()}"
    message[headers.SUBJECT] = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.OriginalUnsubscribeMailto,
        UnsubscribeOriginalData(alias.id, original_recipient, original_subject),
    )
    response = UnsubscribeHandler().handle_unsubscribe_from_message(envelope, message)
    assert status.E202 == response
    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    assert mail_sent.envelope_to == original_recipient
    name, address = parse_full_address(mail_sent.msg[headers.FROM])
    assert name == ""
    assert alias.email == address
    assert mail_sent.msg[headers.TO] == original_recipient
    assert mail_sent.msg[headers.SUBJECT] == original_subject


@mail_sender.store_emails_test_decorator
def test_request_disable_alias(flask_client):
    user = login(flask_client)
    alias = Alias.create_new_random(user)
    Session.commit()
    req_data = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.DisableAlias, alias.id
    )

    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", encoded_request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert not Alias.get(alias.id).enabled
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_request_disable_contact(flask_client):
    user = login(flask_client)
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
    req_data = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.DisableContact, contact.id
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", encoded_request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert Contact.get(contact.id).block_forward
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_request_disable_newsletter(flask_client):
    user = login(flask_client)
    req_data = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.UnsubscribeNewsletter, user.id
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", encoded_request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert not User.get(user.id).notification
    assert 1 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_request_original_unsub(flask_client):
    user = login(flask_client)
    alias = Alias.create_new_random(user)
    Session.commit()

    original_recipient = f"{random()}@out.com"
    original_subject = f"Unsubsomehow{random()}"
    mail_sender.purge_stored_emails()
    req_data = UnsubscribeEncoder.encode_subject(
        UnsubscribeAction.OriginalUnsubscribeMailto,
        UnsubscribeOriginalData(alias.id, original_recipient, original_subject),
    )
    req = flask_client.get(
        url_for("dashboard.encoded_unsubscribe", encoded_request=req_data),
        follow_redirects=True,
    )
    assert 200 == req.status_code
    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    assert mail_sent.envelope_to == original_recipient
    name, address = parse_full_address(mail_sent.msg[headers.FROM])
    assert name == ""
    assert alias.email == address
    assert mail_sent.msg[headers.TO] == original_recipient
    assert mail_sent.msg[headers.SUBJECT] == original_subject
