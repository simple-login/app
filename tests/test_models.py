from uuid import UUID

import pytest

from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN
from app.db import Session
from app.email_utils import parse_full_address
from app.models import (
    generate_email,
    User,
    Alias,
    Contact,
    Mailbox,
    SenderFormatEnum,
    EnumE,
)
from tests.utils import login


def test_generate_email(flask_client):
    email = generate_email()
    assert email.endswith("@" + EMAIL_DOMAIN)

    with pytest.raises(ValueError):
        UUID(email.split("@")[0], version=4)

    email_uuid = generate_email(scheme=2)
    assert UUID(email_uuid.split("@")[0], version=4)


def test_profile_picture_url(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    assert user.profile_picture_url() == "http://sl.test/static/default-avatar.png"


def test_suggested_emails_for_user_who_cannot_create_new_alias(flask_client):
    # make sure user is not in trial
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        trial_end=None,
        commit=True,
    )

    # make sure user runs out of quota to create new email
    for _ in range(MAX_NB_EMAIL_FREE_PLAN):
        Alias.create_new(user=user, prefix="test")
    Session.commit()

    suggested_email, other_emails = user.suggested_emails(website_name="test")

    # the suggested email is chosen from existing Alias
    assert Alias.get_by(email=suggested_email)

    # all other emails are generated emails
    for email in other_emails:
        assert Alias.get_by(email=email)


def test_alias_create_random(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    alias = Alias.create_new_random(user)
    assert alias.email.endswith(EMAIL_DOMAIN)


def test_website_send_to(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    alias = Alias.create_new_random(user)
    Session.commit()

    # non-empty name
    c1 = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
    )
    assert c1.website_send_to() == '"First Last | abcd at example.com" <rep@SL>'

    # empty name, ascii website_from, easy case
    c1.name = None
    c1.website_from = "First Last <abcd@example.com>"
    assert c1.website_send_to() == '"First Last | abcd at example.com" <rep@SL>'

    # empty name, RFC 2047 website_from
    c1.name = None
    c1.website_from = "=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <abcd@example.com>"
    assert c1.website_send_to() == '"Nhơn Nguyễn | abcd at example.com" <rep@SL>'


def test_new_addr_default_sender_format(flask_client):
    user = login(flask_client)
    alias = Alias.first()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == '"First Last - abcd at example.com" <rep@SL>'

    # Make sure email isn't duplicated if sender name equals email
    contact.name = "abcd@example.com"
    assert contact.new_addr() == '"abcd at example.com" <rep@SL>'


def test_new_addr_a_sender_format(flask_client):
    user = login(flask_client)
    user.sender_format = SenderFormatEnum.A.value
    Session.commit()
    alias = Alias.first()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == '"First Last - abcd(a)example.com" <rep@SL>'


def test_new_addr_no_name_sender_format(flask_client):
    user = login(flask_client)
    user.sender_format = SenderFormatEnum.NO_NAME.value
    Session.commit()
    alias = Alias.first()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == "rep@SL"


def test_new_addr_name_only_sender_format(flask_client):
    user = login(flask_client)
    user.sender_format = SenderFormatEnum.NAME_ONLY.value
    Session.commit()
    alias = Alias.first()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == "First Last <rep@SL>"


def test_new_addr_at_only_sender_format(flask_client):
    user = login(flask_client)
    user.sender_format = SenderFormatEnum.AT_ONLY.value
    Session.commit()
    alias = Alias.first()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == '"abcd at example.com" <rep@SL>'


def test_new_addr_unicode(flask_client):
    user = login(flask_client)
    alias = Alias.first()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="Nhơn Nguyễn",
        commit=True,
    )

    assert (
        contact.new_addr()
        == "=?utf-8?q?Nh=C6=A1n_Nguy=E1=BB=85n_-_abcd_at_example=2Ecom?= <rep@SL>"
    )

    # sanity check
    assert parse_full_address(contact.new_addr()) == (
        "Nhơn Nguyễn - abcd at example.com",
        "rep@sl",
    )


def test_mailbox_delete(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    m1 = Mailbox.create(
        user_id=user.id, email="m1@example.com", verified=True, commit=True
    )
    m2 = Mailbox.create(
        user_id=user.id, email="m2@example.com", verified=True, commit=True
    )
    m3 = Mailbox.create(
        user_id=user.id, email="m3@example.com", verified=True, commit=True
    )

    # alias has 2 mailboxes
    alias = Alias.create_new(user, "prefix", mailbox_id=m1.id)
    Session.commit()

    alias._mailboxes.append(m2)
    alias._mailboxes.append(m3)
    Session.commit()

    assert len(alias.mailboxes) == 3

    # delete m1, should not delete alias
    Mailbox.delete(m1.id)
    alias = Alias.get(alias.id)
    assert len(alias.mailboxes) == 2


def test_EnumE():
    class E(EnumE):
        A = 100
        B = 200

    assert E.has_value(100)
    assert not E.has_value(101)

    assert E.get_name(100) == "A"
    assert E.get_name(200) == "B"
    assert E.get_name(101) is None

    assert E.has_name("A")
    assert not E.has_name("Not existent")

    assert E.get_value("A") == 100
    assert E.get_value("Not existent") is None
