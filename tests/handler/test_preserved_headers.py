from aiosmtpd.smtp import Envelope

import email_handler
from app.db import Session
from app.email import headers, status
from app.mail_sender import mail_sender
from app.models import Alias
from app.utils import random_string
from tests.utils import create_new_user, load_eml_file, random_email


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
