from uuid import UUID

import arrow
import pytest

from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN
from app.email_utils import parseaddr_unicode
from app.extensions import db
from app.models import generate_email, User, Alias, Contact


def test_generate_email(flask_client):
    email = generate_email()
    assert email.endswith("@" + EMAIL_DOMAIN)

    with pytest.raises(ValueError):
        UUID(email.split("@")[0], version=4)

    email_uuid = generate_email(scheme=2)
    assert UUID(email_uuid.split("@")[0], version=4)


def test_profile_picture_url(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    assert user.profile_picture_url() == "http://sl.test/static/default-avatar.png"


def test_suggested_emails_for_user_who_cannot_create_new_alias(flask_client):
    # make sure user is not in trial
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        trial_end=None,
    )

    db.session.commit()

    # make sure user runs out of quota to create new email
    for i in range(MAX_NB_EMAIL_FREE_PLAN):
        Alias.create_new(user=user, prefix="test")
    db.session.commit()

    suggested_email, other_emails = user.suggested_emails(website_name="test")

    # the suggested email is chosen from existing Alias
    assert Alias.get_by(email=suggested_email)

    # all other emails are generated emails
    for email in other_emails:
        assert Alias.get_by(email=email)


def test_alias_create_random(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    alias = Alias.create_new_random(user)
    assert alias.email.endswith(EMAIL_DOMAIN)


def test_website_send_to(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

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


def test_new_addr(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    db.session.commit()

    alias = Alias.create_new_random(user)
    db.session.commit()

    # use_via_format_for_sender is by default
    c1 = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="abcd@example.com",
        reply_email="rep@SL",
        name="First Last",
    )
    db.session.commit()
    assert c1.new_addr() == '"abcd@example.com via SimpleLogin" <rep@SL>'

    # use_via_format_for_sender = False
    user.use_via_format_for_sender = False
    db.session.commit()
    assert c1.new_addr() == '"First Last - abcd at example.com" <rep@SL>'

    # unicode name
    c1.name = "Nhơn Nguyễn"
    db.session.commit()
    assert (
        c1.new_addr()
        == "=?utf-8?q?Nh=C6=A1n_Nguy=E1=BB=85n_-_abcd_at_example=2Ecom?= <rep@SL>"
    )

    # sanity check for parseaddr_unicode
    assert parseaddr_unicode(c1.new_addr()) == (
        "Nhơn Nguyễn - abcd at example.com",
        "rep@sl",
    )
