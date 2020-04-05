from email.message import EmailMessage

from app.email_utils import (
    get_email_domain_part,
    email_belongs_to_alias_domains,
    can_be_used_as_personal_email,
    delete_header,
    add_or_replace_header,
    parseaddr_unicode,
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
    assert not can_be_used_as_personal_email("ab@sl.local")
    assert not can_be_used_as_personal_email("hey@d1.test")

    assert can_be_used_as_personal_email("hey@ab.cd")
    # custom domain
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()
    CustomDomain.create(user_id=user.id, domain="ab.cd", verified=True)
    db.session.commit()
    assert not can_be_used_as_personal_email("hey@ab.cd")


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
