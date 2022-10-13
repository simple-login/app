import random
from uuid import UUID

import arrow
import pytest

from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN, NOREPLY
from app.db import Session
from app.email_utils import parse_full_address, generate_reply_email
from app.models import (
    generate_email,
    Alias,
    Contact,
    Mailbox,
    SenderFormatEnum,
    EnumE,
    Subscription,
    PlanEnum,
    PADDLE_SUBSCRIPTION_GRACE_DAYS,
)
from tests.utils import login, create_new_user, random_token


def test_generate_email(flask_client):
    email = generate_email()
    assert email.endswith("@" + EMAIL_DOMAIN)

    with pytest.raises(ValueError):
        UUID(email.split("@")[0], version=4)

    email_uuid = generate_email(scheme=2)
    assert UUID(email_uuid.split("@")[0], version=4)


def test_profile_picture_url(flask_client):
    user = create_new_user()

    assert user.profile_picture_url() == "http://sl.test/static/default-avatar.png"


def test_suggested_emails_for_user_who_cannot_create_new_alias(flask_client):
    # make sure user is not in trial
    user = create_new_user()
    user.trial_end = None

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
    user = create_new_user()

    alias = Alias.create_new_random(user)
    assert alias.email.endswith(EMAIL_DOMAIN)


def test_website_send_to(flask_client):
    user = create_new_user()

    alias = Alias.create_new_random(user)
    Session.commit()

    prefix = random_token()

    # non-empty name
    c1 = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
        reply_email="rep@SL",
        name="First Last",
    )
    assert c1.website_send_to() == f'"First Last | {prefix} at example.com" <rep@SL>'

    # empty name, ascii website_from, easy case
    c1.name = None
    c1.website_from = f"First Last <{prefix}@example.com>"
    assert c1.website_send_to() == f'"First Last | {prefix} at example.com" <rep@SL>'

    # empty name, RFC 2047 website_from
    c1.name = None
    c1.website_from = f"=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <{prefix}@example.com>"
    assert c1.website_send_to() == f'"Nhơn Nguyễn | {prefix} at example.com" <rep@SL>'


def test_new_addr_default_sender_format(flask_client):
    user = login(flask_client)
    alias = Alias.first()
    prefix = random_token()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == f'"First Last - {prefix} at example.com" <rep@SL>'

    # Make sure email isn't duplicated if sender name equals email
    contact.name = f"{prefix}@example.com"
    assert contact.new_addr() == f'"{prefix} at example.com" <rep@SL>'


def test_new_addr_a_sender_format(flask_client):
    user = login(flask_client)
    user.sender_format = SenderFormatEnum.A.value
    Session.commit()
    alias = Alias.first()
    prefix = random_token()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == f'"First Last - {prefix}(a)example.com" <rep@SL>'


def test_new_addr_no_name_sender_format(flask_client):
    user = login(flask_client)
    user.sender_format = SenderFormatEnum.NO_NAME.value
    Session.commit()
    alias = Alias.first()
    prefix = random_token()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
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
    prefix = random_token()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
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
    prefix = random_token()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
        reply_email="rep@SL",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == f'"{prefix} at example.com" <rep@SL>'


def test_new_addr_unicode(flask_client):
    user = login(flask_client)
    alias = Alias.first()

    random_prefix = random_token()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{random_prefix}@example.com",
        reply_email="rep@SL",
        name="Nhơn Nguyễn",
        commit=True,
    )

    assert (
        contact.new_addr()
        == f"=?utf-8?q?Nh=C6=A1n_Nguy=E1=BB=85n_-_{random_prefix}_at_example=2Ecom?= <rep@SL>"
    )

    # sanity check
    assert parse_full_address(contact.new_addr()) == (
        f"Nhơn Nguyễn - {random_prefix} at example.com",
        "rep@sl",
    )


def test_mailbox_delete(flask_client):
    user = create_new_user()

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


def test_can_create_new_alias_disabled_user():
    user = create_new_user()
    assert user.can_create_new_alias()

    user.disabled = True
    assert not user.can_create_new_alias()


def test_user_get_subscription_grace_period(flask_client):
    user = create_new_user()
    sub = Subscription.create(
        user_id=user.id,
        cancel_url="https://checkout.paddle.com/subscription/cancel?user=1234",
        update_url="https://checkout.paddle.com/subscription/update?user=1234",
        subscription_id=str(random.random()),
        event_time=arrow.now(),
        next_bill_date=arrow.now().shift(days=-PADDLE_SUBSCRIPTION_GRACE_DAYS).date(),
        plan=PlanEnum.monthly,
        commit=True,
    )

    assert user.get_paddle_subscription() is not None

    sub.next_bill_date = (
        arrow.now().shift(days=-(PADDLE_SUBSCRIPTION_GRACE_DAYS + 1)).date()
    )
    assert user.get_paddle_subscription() is None


def test_create_contact_for_noreply(flask_client):
    user = create_new_user()
    alias = Alias.filter(Alias.user_id == user.id).first()

    # create a contact with NOREPLY as reply_email
    Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{random.random()}@contact.test",
        reply_email=NOREPLY,
        commit=True,
    )

    # create a contact for NOREPLY shouldn't raise CannotCreateContactForReverseAlias
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=NOREPLY,
        reply_email=generate_reply_email(NOREPLY, user),
    )
    assert contact.website_email == NOREPLY
