from email.message import EmailMessage

from aiosmtpd.smtp import Envelope

import email_handler
from app.email import headers, status
from app.models import User, Alias, AuthorizedAddress, IgnoredEmail, EmailLog
from email_handler import (
    get_mailbox_from_mail_from,
    should_ignore,
    is_automatic_out_of_office,
)
from tests.utils import load_eml_file, create_random_user


def test_get_mailbox_from_mail_from(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email="first@d1.test",
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    mb = get_mailbox_from_mail_from("a@b.c", alias)
    assert mb.email == "a@b.c"

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
    assert mb.email == "a@b.c"


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


def test_process_spoofed(flask_client):
    user = create_random_user()
    alias = Alias.create_new_random(user)
    msg = load_eml_file("gmail_spoof.eml", {"alias_email": alias.email})
    envelope = Envelope()
    envelope.mail_from = msg["from"]
    envelope.rcpt_tos = [msg["to"]]
    result = email_handler.handle(envelope, msg)
    assert result == status.E519
    email_logs = (
        EmailLog.filter_by(user_id=user.id, alias_id=alias.id)
        .order_by(EmailLog.id.desc())
        .all()
    )
    assert len(email_logs) == 1
    email_log = email_logs[0]
    assert email_log.blocked
    assert email_log.refused_email_id
