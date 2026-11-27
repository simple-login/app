from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr

import pytest
from aiosmtpd.smtp import Envelope

import email_handler
from app import config
from app.db import Session
from app.email import headers, status
from app.mail_sender import mail_sender
from app.message_utils import message_to_bytes
from app.models import Alias, Contact
from app.utils import random_string
from tests.utils import create_new_user, load_eml_file, random_email


@pytest.mark.parametrize("is_reply", [False, True], ids=["forward", "reply"])
@pytest.mark.parametrize(
    "auto_submitted, auto_response_suppress, reply_auto_submitted",
    [
        ("auto-replied", "All", "auto-replied"),
        ("auto-generated", None, "auto-generated"),
        (None, "OOF, AutoReply", None),
        ("no", "None", "no"),
        (None, None, None),
        (
            r"(owner {mailbox_email} (nested\) comment)) auto-replied (private)",
            "All",
            "auto-replied",
        ),
        (
            'auto-notified; owner-email="{mailbox_email}"; owner-token=private',
            None,
            'auto-notified; owner-email="{alias_email}"',
        ),
    ],
)
@mail_sender.store_emails_test_decorator
def test_auto_response_headers_preserved(
    flask_client, is_reply, auto_submitted, auto_response_suppress, reply_auto_submitted
):
    user = create_new_user()
    user.include_header_email_header = False
    alias = Alias.create_new_random(user)
    Session.flush()

    if is_reply:
        contact = Contact.create(
            user_id=user.id,
            alias_id=alias.id,
            website_email=random_email(),
            reply_email=f"{random_string(10)}@{config.EMAIL_DOMAIN}",
            flush=True,
        )
        sender = alias.mailbox.email
        recipient = contact.reply_email
        destination = contact.website_email
    else:
        sender = random_email()
        recipient = alias.email
        destination = alias.mailbox.email

    if auto_submitted is not None:
        auto_submitted = auto_submitted.format(mailbox_email=sender)
    if is_reply and reply_auto_submitted is not None:
        reply_auto_submitted = reply_auto_submitted.format(alias_email=alias.email)

    msg = EmailMessage()
    msg[headers.FROM] = sender
    msg[headers.TO] = recipient
    msg[headers.SUBJECT] = "Automatic response header preservation"
    msg[headers.DATE] = "Wed, 28 Oct 2026 12:00:00 +0000"
    msg[headers.IN_REPLY_TO] = "<original@example.com>"
    msg[headers.REFERENCES] = "<original@example.com>"
    # Header names are case insensitive, including those supplied by mail clients.
    if auto_submitted is not None:
        msg["auto-submitted"] = auto_submitted
    if auto_response_suppress is not None:
        msg["x-auto-response-suppress"] = auto_response_suppress
    msg[headers.RECEIVED] = "from private-host.example.com (192.0.2.1)"
    msg["X-Originating-IP"] = "[192.0.2.1]"
    msg["X-Mailer"] = "Private mail client"
    msg[headers.AUTHENTICATION_RESULTS] = "private-host.example.com; spf=pass"
    msg.set_content("Message body.\n")

    envelope = Envelope()
    envelope.mail_from = sender
    envelope.rcpt_tos = [recipient]
    assert email_handler.handle(envelope, msg) == status.E200

    send_requests = mail_sender.get_stored_emails()
    assert len(send_requests) == 1
    request = send_requests[0]
    assert request.envelope_to == destination
    assert request.is_forward == (not is_reply)
    # Inspect the serialized delivery, not just the original message object.
    sent_msg = message_from_bytes(message_to_bytes(request.msg), policy=policy.default)
    for header, value in (
        ("Auto-Submitted", reply_auto_submitted if is_reply else auto_submitted),
        ("X-Auto-Response-Suppress", auto_response_suppress),
    ):
        assert sent_msg.get_all(header) == ([value] if value is not None else None)
    assert sent_msg[headers.SUBJECT] == "Automatic response header preservation"
    assert sent_msg[headers.DATE] == "Wed, 28 Oct 2026 12:00:00 +0000"
    assert sent_msg[headers.IN_REPLY_TO] == "<original@example.com>"
    assert sent_msg[headers.REFERENCES] == "<original@example.com>"
    assert sent_msg.get_payload(decode=True) == b"Message body.\n"
    assert parseaddr(sent_msg[headers.FROM])[1] != sender
    assert parseaddr(sent_msg[headers.TO])[1] == (
        destination if is_reply else alias.email
    )
    for header in (
        headers.RECEIVED,
        "X-Originating-IP",
        "X-Mailer",
        headers.AUTHENTICATION_RESULTS,
    ):
        assert header not in sent_msg
    if is_reply:
        assert sender not in str(sent_msg)
        assert "owner-token" not in str(sent_msg)
        assert "private" not in str(sent_msg)


@pytest.mark.parametrize("is_reply", [False, True], ids=["forward", "reply"])
@mail_sender.store_emails_test_decorator
def test_auto_response_headers_preserved_after_verp_remap(flask_client, is_reply):
    user = create_new_user()
    user.include_header_email_header = False
    alias = Alias.create_new_random(user)
    Session.flush()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=random_email(),
        reply_email=f"{random_string(10)}@{config.EMAIL_DOMAIN}",
        flush=True,
    )
    # First send in the opposite direction to obtain a real delivery VERP.
    initial_sender = contact.website_email if is_reply else alias.mailbox.email
    initial_recipient = alias.email if is_reply else contact.reply_email
    original = EmailMessage()
    original[headers.FROM] = initial_sender
    original[headers.TO] = initial_recipient
    original[headers.SUBJECT] = "Original message"
    original.set_content("Original message body.\n")
    envelope = Envelope()
    envelope.mail_from = initial_sender
    envelope.rcpt_tos = [initial_recipient]
    assert email_handler.handle(envelope, original) == status.E200
    original_requests = mail_sender.get_stored_emails()
    assert len(original_requests) == 1
    original_request = original_requests[0]
    mail_sender.purge_stored_emails()

    response = EmailMessage()
    response[headers.FROM] = original_request.envelope_to
    response[headers.TO] = original_request.envelope_from
    response[headers.SUBJECT] = "Automatic reply"
    response[headers.AUTO_SUBMITTED] = "auto-replied"
    response[headers.X_AUTO_RESPONSE_SUPPRESS] = "All"
    response.set_content("I am away.\n")
    envelope = Envelope()
    envelope.mail_from = original_request.envelope_to
    envelope.rcpt_tos = [original_request.envelope_from]
    assert email_handler.handle(envelope, response) == status.E200

    send_requests = mail_sender.get_stored_emails()
    assert len(send_requests) == 1
    request = send_requests[0]
    assert request.envelope_to == initial_sender
    assert request.is_forward == (not is_reply)
    sent_msg = message_from_bytes(message_to_bytes(request.msg))
    assert sent_msg.get_all(headers.AUTO_SUBMITTED) == ["auto-replied"]
    assert sent_msg.get_all(headers.X_AUTO_RESPONSE_SUPPRESS) == ["All"]


@mail_sender.store_emails_test_decorator
def test_original_headers_from_preserved():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.flush()
    assert user.include_header_email_header
    original_sender_address = random_email()
    msg = load_eml_file(
        "replacement_on_forward_phase.eml",
        {
            "sender_address": original_sender_address,
            "recipient_address": alias.email,
            "cc_address": random_email(),
        },
    )
    envelope = Envelope()
    envelope.mail_from = f"env.{original_sender_address}"
    envelope.rcpt_tos = [alias.email]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E200
    send_requests = mail_sender.get_stored_emails()
    assert len(send_requests) == 1
    request = send_requests[0]
    assert request.msg[headers.SL_ENVELOPE_FROM] == envelope.mail_from
    assert request.msg[headers.SL_ORIGINAL_FROM] == original_sender_address
    assert (
        request.msg[headers.AUTHENTICATION_RESULTS]
        == msg[headers.AUTHENTICATION_RESULTS]
    )


@mail_sender.store_emails_test_decorator
def test_original_headers_from_with_name_preserved():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.flush()
    assert user.include_header_email_header
    original_sender_address = random_email()
    name = random_string(10)
    msg = load_eml_file(
        "replacement_on_forward_phase.eml",
        {
            "sender_address": f"{name} <{original_sender_address}>",
            "recipient_address": alias.email,
            "cc_address": random_email(),
        },
    )
    envelope = Envelope()
    envelope.mail_from = f"env.{original_sender_address}"
    envelope.rcpt_tos = [alias.email]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E200
    send_requests = mail_sender.get_stored_emails()
    assert len(send_requests) == 1
    request = send_requests[0]
    assert request.msg[headers.SL_ENVELOPE_FROM] == envelope.mail_from
    assert (
        request.msg[headers.SL_ORIGINAL_FROM] == f"{name} <{original_sender_address}>"
    )
    assert (
        request.msg[headers.AUTHENTICATION_RESULTS]
        == msg[headers.AUTHENTICATION_RESULTS]
    )
