import random
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from typing import List

import arrow
import pytest
from aiosmtpd.smtp import Envelope

import email_handler
from app import config
from app.config import EMAIL_DOMAIN, ALERT_DMARC_FAILED_REPLY_PHASE
from app.db import Session
from app.email import headers, status
from app.email_utils import generate_verp_email
from app.mail_sender import mail_sender
from app.models import (
    Alias,
    IgnoredEmail,
    EmailLog,
    Notification,
    VerpType,
    Contact,
    SentAlert,
)
from app.utils import random_string, canonicalize_email
from email_handler import (
    should_ignore,
    is_automatic_out_of_office,
)
from tests.utils import load_eml_file, create_new_user, random_email


def test_should_ignore(flask_client):
    IgnoredEmail.filter_by(rcpt_to="rcpt_to").delete()

    assert should_ignore("mail_from", []) is False

    assert not should_ignore("mail_from", ["rcpt_to"])
    IgnoredEmail.create(mail_from="mail_from", rcpt_to="rcpt_to", commit=True)
    assert should_ignore("mail_from", ["rcpt_to"])


def test_is_automatic_out_of_office():
    msg = EmailMessage()
    assert not is_automatic_out_of_office(msg)

    msg[headers.AUTO_SUBMITTED] = "auto-replied"
    assert is_automatic_out_of_office(msg)

    del msg[headers.AUTO_SUBMITTED]
    assert not is_automatic_out_of_office(msg)

    msg[headers.AUTO_SUBMITTED] = "auto-generated"
    assert is_automatic_out_of_office(msg)


def test_dmarc_forward_quarantine(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file("dmarc_quarantine.eml", {"alias_email": alias.email})
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.handle(envelope, msg)
    assert result == status.E215
    email_logs = (
        EmailLog.filter_by(user_id=user.id, alias_id=alias.id)
        .order_by(EmailLog.id.desc())
        .all()
    )
    assert len(email_logs) == 1
    email_log = email_logs[0]
    assert email_log.blocked
    assert email_log.refused_email_id
    notifications = Notification.filter_by(user_id=user.id).all()
    assert len(notifications) == 1
    assert f"{alias.email} has a new mail in quarantine" == notifications[0].title


def test_gmail_dmarc_softfail(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file("dmarc_gmail_softfail.eml", {"alias_email": alias.email})
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.handle(envelope, msg)
    assert result == status.E200
    # Enable when we can verify that the actual message sent has this content
    # payload = msg.get_payload()
    # assert payload.find("failed anti-phishing checks") > -1


def test_prevent_5xx_from_spf(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file(
        "5xx_overwrite_spf.eml",
        {"alias_email": alias.email, "spf_result": "R_SPF_FAIL"},
    )
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    # Ensure invalid email log
    envelope.rcpt_tos = [generate_verp_email(VerpType.bounce_forward, 99999999999999)]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert status.E216 == result


def test_preserve_5xx_with_valid_spf(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file(
        "5xx_overwrite_spf.eml",
        {"alias_email": alias.email, "spf_result": "R_SPF_ALLOW"},
    )
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    # Ensure invalid email log
    envelope.rcpt_tos = [generate_verp_email(VerpType.bounce_forward, 99999999999999)]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert status.E512 == result


def test_preserve_5xx_with_no_header(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file(
        "no_spamd_header.eml",
        {"alias_email": alias.email},
    )
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    # Ensure invalid email log
    envelope.rcpt_tos = [generate_verp_email(VerpType.bounce_forward, 99999999999999)]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert status.E512 == result


def generate_dmarc_result() -> List:
    return ["DMARC_POLICY_QUARANTINE", "DMARC_POLICY_REJECT", "DMARC_POLICY_SOFTFAIL"]


@pytest.mark.parametrize("dmarc_result", generate_dmarc_result())
def test_dmarc_reply_quarantine(flask_client, dmarc_result):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=alias.user_id,
        alias_id=alias.id,
        website_email="random-{}@nowhere.net".format(int(random.random())),
        name="Name {}".format(int(random.random())),
        reply_email="random-{}@{}".format(random.random(), EMAIL_DOMAIN),
    )
    Session.commit()
    msg = load_eml_file(
        "dmarc_reply_check.eml",
        {
            "alias_email": alias.email,
            "contact_email": contact.reply_email,
            "dmarc_result": dmarc_result,
        },
    )
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.handle(envelope, msg)
    assert result == status.E215
    alerts = SentAlert.filter_by(
        user_id=user.id, alert_type=ALERT_DMARC_FAILED_REPLY_PHASE
    ).all()
    assert len(alerts) == 1


def test_add_alias_to_header_if_needed():
    msg = EmailMessage()
    user = create_new_user()
    alias = Alias.filter_by(user_id=user.id).first()

    assert msg[headers.TO] is None

    email_handler.add_alias_to_header_if_needed(msg, alias)

    assert msg[headers.TO] == alias.email


def test_append_alias_to_header_if_needed_existing_to():
    msg = EmailMessage()
    original_to = "noone@nowhere.no"
    msg[headers.TO] = original_to
    user = create_new_user()
    alias = Alias.filter_by(user_id=user.id).first()
    email_handler.add_alias_to_header_if_needed(msg, alias)
    assert msg[headers.TO] == f"{original_to}, {alias.email}"


def test_avoid_add_to_header_already_present():
    msg = EmailMessage()
    user = create_new_user()
    alias = Alias.filter_by(user_id=user.id).first()
    msg[headers.TO] = alias.email
    email_handler.add_alias_to_header_if_needed(msg, alias)
    assert msg[headers.TO] == alias.email


def test_avoid_add_to_header_already_present_in_cc():
    msg = EmailMessage()
    create_new_user()
    alias = Alias.first()
    msg[headers.CC] = alias.email
    email_handler.add_alias_to_header_if_needed(msg, alias)
    assert msg[headers.TO] is None
    assert msg[headers.CC] == alias.email


def test_email_sent_to_noreply(flask_client):
    msg = EmailMessage()
    envelope = Envelope()
    envelope.mail_from = "from@domain.lan"
    envelope.rcpt_tos = [config.NOREPLY]
    result = email_handler.handle(envelope, msg)
    assert result == status.E200


def test_email_sent_to_noreplies(flask_client):
    msg = EmailMessage()
    envelope = Envelope()
    envelope.mail_from = "from@domain.lan"
    config.NOREPLIES = ["other-no-reply@sl.lan"]

    envelope.rcpt_tos = ["other-no-reply@sl.lan"]
    result = email_handler.handle(envelope, msg)
    assert result == status.E200

    # NOREPLY isn't used anymore
    envelope.rcpt_tos = [config.NOREPLY]
    result = email_handler.handle(envelope, msg)
    assert result == status.E515


def test_references_header(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file("reference_encoded.eml", {"alias_email": alias.email})
    envelope = Envelope()
    envelope.mail_from = "somewhere@rainbow.com"
    envelope.rcpt_tos = [alias.email]
    result = email_handler.handle(envelope, msg)
    assert result == status.E200


@mail_sender.store_emails_test_decorator
def test_replace_contacts_and_user_in_reply_phase(flask_client):
    user = create_new_user()
    user.replace_reverse_alias = True
    alias = Alias.create_new_random(user)
    Session.flush()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=random_email(),
        reply_email=f"{random.random()}@{EMAIL_DOMAIN}",
        commit=True,
    )
    contact_real_mail = contact.website_email
    contact2 = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=random_email(),
        reply_email=f"{random.random()}@{EMAIL_DOMAIN}",
        commit=True,
    )
    contact2_real_mail = contact2.website_email
    msg = load_eml_file(
        "replacement_on_reply_phase.eml",
        {
            "contact_reply_email": contact.reply_email,
            "other_contact_reply_email": contact2.reply_email,
        },
    )
    envelope = Envelope()
    envelope.mail_from = alias.mailbox.email
    envelope.rcpt_tos = [contact.reply_email]
    result = email_handler.handle(envelope, msg)
    assert result == status.E200
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    payload = sent_mails[0].msg.get_payload()[0].get_payload()
    assert payload.find("Contact is {}".format(contact_real_mail)) > -1
    assert payload.find("Other contact is {}".format(contact2_real_mail)) > -1


@mail_sender.store_emails_test_decorator
def test_send_email_from_non_canonical_address_on_reply(flask_client):
    email_address = f"{random_string(10)}.suf@gmail.com"
    user = create_new_user(email=canonicalize_email(email_address))
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=random_email(),
        reply_email=f"{random_string(10)}@{EMAIL_DOMAIN}",
        commit=True,
    )
    envelope = Envelope()
    envelope.mail_from = email_address
    envelope.rcpt_tos = [contact.reply_email]
    msg = EmailMessage()
    msg[headers.TO] = contact.reply_email
    msg[headers.SUBJECT] = random_string()
    result = email_handler.handle(envelope, msg)
    assert result == status.E200
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    email_logs = EmailLog.filter_by(user_id=user.id).all()
    assert len(email_logs) == 1
    assert email_logs[0].alias_id == alias.id
    assert email_logs[0].mailbox_id == user.default_mailbox_id


@mail_sender.store_emails_test_decorator
def test_send_email_from_non_canonical_matches_already_existing_user(flask_client):
    email_address = f"{random_string(10)}.suf@gmail.com"
    create_new_user(email=canonicalize_email(email_address))
    user = create_new_user(email=email_address)
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=random_email(),
        reply_email=f"{random_string(10)}@{EMAIL_DOMAIN}",
        commit=True,
    )
    envelope = Envelope()
    envelope.mail_from = email_address
    envelope.rcpt_tos = [contact.reply_email]
    msg = EmailMessage()
    msg[headers.TO] = contact.reply_email
    msg[headers.SUBJECT] = random_string()
    result = email_handler.handle(envelope, msg)
    assert result == status.E200
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    email_logs = EmailLog.filter_by(user_id=user.id).all()
    assert len(email_logs) == 1
    assert email_logs[0].alias_id == alias.id
    assert email_logs[0].mailbox_id == user.default_mailbox_id


@mail_sender.store_emails_test_decorator
def test_break_loop_alias_as_mailbox(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.default_mailbox.email = alias.email
    Session.commit()
    envelope = Envelope()
    envelope.mail_from = random_email()
    envelope.rcpt_tos = [alias.email]
    msg = EmailMessage()
    msg[headers.TO] = alias.email
    msg[headers.SUBJECT] = random_string()
    result = email_handler.handle(envelope, msg)
    assert result == status.E525


@mail_sender.store_emails_test_decorator
def test_preserve_headers(flask_client):
    headers_to_keep = [
        headers.SUBJECT,
        headers.DATE,
        headers.MESSAGE_ID,
        headers.REFERENCES,
        headers.IN_REPLY_TO,
        headers.SL_QUEUE_ID,
    ] + headers.MIME_HEADERS
    user = create_new_user()
    alias = Alias.create_new_random(user)
    envelope = Envelope()
    envelope.mail_from = "somewhere@lo.cal"
    envelope.rcpt_tos = [alias.email]
    msg = EmailMessage()
    for header in headers_to_keep:
        msg[header] = header + "keep"
    result = email_handler.handle(envelope, msg)
    assert result == status.E200
    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    msg = sent_mails[0].msg
    for header in headers_to_keep:
        assert msg[header] == header + "keep"


def test_not_send_to_pending_to_delete_users(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.delete_on = arrow.utcnow()
    envelope = Envelope()
    envelope.mail_from = "somewhere@lo.cal"
    envelope.rcpt_tos = [alias.email]
    msg = EmailMessage()
    result = email_handler.handle(envelope, msg)
    assert result == status.E504


@mail_sender.store_emails_test_decorator
def test_forward_preserves_pgp_key_attachment(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()

    msg = MIMEMultipart("mixed")
    msg[headers.FROM] = "sender@external.com"
    msg[headers.TO] = alias.email
    msg[headers.SUBJECT] = "Signed message with public key"
    msg.attach(MIMEText("Hello, here is my signed message.", "plain"))

    pgp_key = MIMEBase("application", "pgp-keys")
    pgp_key.set_payload(
        b"-----BEGIN PGP PUBLIC KEY BLOCK-----\nfake\n-----END PGP PUBLIC KEY BLOCK-----"
    )
    pgp_key.add_header(
        "Content-Disposition",
        "attachment",
        filename="publickey - sender@external.com.asc",
    )
    msg.attach(pgp_key)

    envelope = Envelope()
    envelope.mail_from = "sender@external.com"
    envelope.rcpt_tos = [alias.email]

    result = email_handler.handle(envelope, msg)
    assert result == status.E200

    sent_mails = mail_sender.get_stored_emails()
    assert len(sent_mails) == 1
    forwarded_msg = sent_mails[0].msg

    # The PGP public key attachment should still be present in the forwarded email
    attachments = [
        part
        for part in forwarded_msg.walk()
        if part.get_content_type() == "application/pgp-keys"
    ]
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "publickey - sender@external.com.asc"


def _create_reply_with_pgp_key_attachment(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    Session.commit()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=random_email(),
        reply_email=f"{random_string(10)}@{EMAIL_DOMAIN}",
        commit=True,
    )

    msg = MIMEMultipart("mixed")
    msg[headers.TO] = contact.reply_email
    msg[headers.SUBJECT] = "Re: signed reply"
    msg.attach(MIMEText("Here is my reply.", "plain"))

    pgp_key = MIMEBase("application", "pgp-keys")
    pgp_key.set_payload(
        b"-----BEGIN PGP PUBLIC KEY BLOCK-----\nfake\n-----END PGP PUBLIC KEY BLOCK-----"
    )
    pgp_key.add_header(
        "Content-Disposition",
        "attachment",
        filename=f"publickey - {user.email}.asc",
    )
    msg.attach(pgp_key)

    envelope = Envelope()
    envelope.mail_from = user.email
    envelope.rcpt_tos = [contact.reply_email]

    return user, msg, envelope


@mail_sender.store_emails_test_decorator
def test_reply_strips_pgp_key_when_config_enabled(flask_client):
    # Verify that when DROP_PGP_KEY_ATTACHMENTS_ON_REPLY is enabled,
    # PGP public key attachments should be removed from replies
    original = config.DROP_PGP_KEY_ATTACHMENTS_ON_REPLY
    config.DROP_PGP_KEY_ATTACHMENTS_ON_REPLY = True
    try:
        _, msg, envelope = _create_reply_with_pgp_key_attachment(flask_client)
        result = email_handler.handle(envelope, msg)
        assert result == status.E200

        sent_mails = mail_sender.get_stored_emails()
        assert len(sent_mails) == 1
        reply_msg = sent_mails[0].msg

        pgp_attachments = [
            part
            for part in reply_msg.walk()
            if part.get_content_type() == "application/pgp-keys"
        ]
        assert len(pgp_attachments) == 0
    finally:
        config.DROP_PGP_KEY_ATTACHMENTS_ON_REPLY = original


@mail_sender.store_emails_test_decorator
def test_reply_preserves_pgp_key_when_config_disabled(flask_client):
    # Verify that when DROP_PGP_KEY_ATTACHMENTS_ON_REPLY is disabled (default),
    # PGP public key attachments should be preserved in replies
    original = config.DROP_PGP_KEY_ATTACHMENTS_ON_REPLY
    config.DROP_PGP_KEY_ATTACHMENTS_ON_REPLY = False
    try:
        user, msg, envelope = _create_reply_with_pgp_key_attachment(flask_client)
        result = email_handler.handle(envelope, msg)
        assert result == status.E200

        sent_mails = mail_sender.get_stored_emails()
        assert len(sent_mails) == 1
        reply_msg = sent_mails[0].msg

        pgp_attachments = [
            part
            for part in reply_msg.walk()
            if part.get_content_type() == "application/pgp-keys"
        ]
        assert len(pgp_attachments) == 1
        assert pgp_attachments[0].get_filename() == f"publickey - {user.email}.asc"
    finally:
        config.DROP_PGP_KEY_ATTACHMENTS_ON_REPLY = original
