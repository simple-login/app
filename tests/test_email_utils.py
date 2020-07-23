import email
from email.message import EmailMessage

from app.config import MAX_ALERT_24H
from app.email_utils import (
    get_email_domain_part,
    email_belongs_to_alias_domains,
    email_domain_can_be_used_as_mailbox,
    delete_header,
    add_or_replace_header,
    parseaddr_unicode,
    send_email_with_rate_control,
    copy,
    get_spam_from_header,
)
from app.extensions import db
from app.models import User, CustomDomain


def test_get_email_domain_part():
    assert get_email_domain_part("ab@cd.com") == "cd.com"


def test_email_belongs_to_alias_domains():
    # default alias domain
    assert email_belongs_to_alias_domains("ab@sl.local")
    assert not email_belongs_to_alias_domains("ab@not-exist.local")

    assert email_belongs_to_alias_domains("hey@d1.test")
    assert not email_belongs_to_alias_domains("hey@d3.test")


def test_can_be_used_as_personal_email(flask_client):
    # default alias domain
    assert not email_domain_can_be_used_as_mailbox("ab@sl.local")
    assert not email_domain_can_be_used_as_mailbox("hey@d1.test")

    assert email_domain_can_be_used_as_mailbox("hey@ab.cd")
    # custom domain
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()
    CustomDomain.create(user_id=user.id, domain="ab.cd", verified=True)
    db.session.commit()
    assert not email_domain_can_be_used_as_mailbox("hey@ab.cd")

    # disposable domain
    assert not email_domain_can_be_used_as_mailbox("abcd@10minutesmail.fr")
    assert not email_domain_can_be_used_as_mailbox("abcd@temp-mail.com")
    # subdomain will not work
    assert not email_domain_can_be_used_as_mailbox("abcd@sub.temp-mail.com")
    # valid domains should not be affected
    assert email_domain_can_be_used_as_mailbox("abcd@protonmail.com")
    assert email_domain_can_be_used_as_mailbox("abcd@gmail.com")
    assert email_domain_can_be_used_as_mailbox("abcd@example.com")


def test_delete_header():
    msg = EmailMessage()
    assert msg._headers == []

    msg["H"] = "abcd"
    msg["H"] = "xyzt"

    assert msg._headers == [("H", "abcd"), ("H", "xyzt")]

    delete_header(msg, "H")
    assert msg._headers == []


def test_add_or_replace_header():
    msg = EmailMessage()
    msg["H"] = "abcd"
    msg["H"] = "xyzt"
    assert msg._headers == [("H", "abcd"), ("H", "xyzt")]

    add_or_replace_header(msg, "H", "new")
    assert msg._headers == [("H", "new")]


def test_parseaddr_unicode():
    # only email
    assert parseaddr_unicode("abcd@gmail.com") == ("", "abcd@gmail.com",)

    # ascii address
    assert parseaddr_unicode("First Last <abcd@gmail.com>") == (
        "First Last",
        "abcd@gmail.com",
    )

    # Handle quote
    assert parseaddr_unicode('"First Last" <abcd@gmail.com>') == (
        "First Last",
        "abcd@gmail.com",
    )

    # UTF-8 charset
    assert parseaddr_unicode("=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <abcd@gmail.com>") == (
        "Nhơn Nguyễn",
        "abcd@gmail.com",
    )

    # iso-8859-1 charset
    assert parseaddr_unicode("=?iso-8859-1?q?p=F6stal?= <abcd@gmail.com>") == (
        "pöstal",
        "abcd@gmail.com",
    )


def test_send_email_with_rate_control(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    for _ in range(MAX_ALERT_24H):
        assert send_email_with_rate_control(
            user, "test alert type", "abcd@gmail.com", "subject", "plaintext"
        )
    assert not send_email_with_rate_control(
        user, "test alert type", "abcd@gmail.com", "subject", "plaintext"
    )


def test_copy():
    email_str = """
    From: abcd@gmail.com
    To: hey@example.org
    Subject: subject
    
    Body    
    """
    msg = email.message_from_string(email_str)
    msg2 = copy(msg)

    assert msg.as_bytes() == msg2.as_bytes()


def test_get_spam_from_header():
    is_spam, _ = get_spam_from_header(
        """No, score=-0.1 required=5.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2"""
    )
    assert not is_spam

    is_spam, _ = get_spam_from_header(
        """Yes, score=-0.1 required=5.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2"""
    )
    assert is_spam

    # the case where max_score is less than the default used by SpamAssassin
    is_spam, _ = get_spam_from_header(
        """No, score=6 required=10.0 tests=DKIM_SIGNED,DKIM_VALID,
  DKIM_VALID_AU,RCVD_IN_DNSWL_BLOCKED,RCVD_IN_MSPIKE_H2,SPF_PASS,
  URIBL_BLOCKED autolearn=unavailable autolearn_force=no version=3.4.2""",
        max_score=5,
    )
    assert is_spam
