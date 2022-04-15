import random
from email.message import EmailMessage
from typing import List

import pytest
from aiosmtpd.smtp import Envelope

import email_handler
from app.config import BOUNCE_EMAIL, EMAIL_DOMAIN, ALERT_DMARC_FAILED_REPLY_PHASE
from app.db import Session
from app.email import headers, status
from app.models import (
    Alias,
    AuthorizedAddress,
    IgnoredEmail,
    EmailLog,
    Notification,
    Contact,
    SentAlert,
)
from email_handler import (
    get_mailbox_from_mail_from,
    should_ignore,
    is_automatic_out_of_office,
)
from tests.utils import load_eml_file, create_new_user


def test_get_mailbox_from_mail_from(flask_client):
    user = create_new_user()
    alias = Alias.create(
        user_id=user.id,
        email="first@d1.test",
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    mb = get_mailbox_from_mail_from(user.email, alias)
    assert mb.email == user.email

    mb = get_mailbox_from_mail_from("unauthorized@gmail.com", alias)
    assert mb is None

    # authorized address
    AuthorizedAddress.create(
        user_id=user.id,
        mailbox_id=user.default_mailbox_id,
        email="unauthorized@gmail.com",
        commit=True,
    )
    mb = get_mailbox_from_mail_from("unauthorized@gmail.com", alias)
    assert mb.email == user.email


def test_should_ignore(flask_client):
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
    envelope.mail_from = BOUNCE_EMAIL.format(999999999999999999)
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E216


def test_preserve_5xx_with_valid_spf(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file(
        "5xx_overwrite_spf.eml",
        {"alias_email": alias.email, "spf_result": "R_SPF_ALLOW"},
    )
    envelope = Envelope()
    envelope.mail_from = BOUNCE_EMAIL.format(999999999999999999)
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E512


def test_preserve_5xx_with_no_header(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file(
        "no_spamd_header.eml",
        {"alias_email": alias.email},
    )
    envelope = Envelope()
    envelope.mail_from = BOUNCE_EMAIL.format(999999999999999999)
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E512


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
