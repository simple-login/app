import random
from uuid import UUID

import arrow
import pytest

from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN
from app.email_utils import get_noreply_email
from app.db import Session
from app.email_utils import parse_full_address, generate_reply_email
from app.models import (
    generate_random_alias_email,
    Alias,
    Contact,
    EmailLog,
    Mailbox,
    SenderFormatEnum,
    EnumE,
    Subscription,
    PlanEnum,
    PADDLE_SUBSCRIPTION_GRACE_DAYS,
    SyncEvent,
)
from tests.utils import login, create_new_user, random_token


def test_generate_email(flask_client):
    email = generate_random_alias_email()
    assert email.endswith("@" + EMAIL_DOMAIN)

    with pytest.raises(ValueError):
        UUID(email.split("@")[0], version=4)

    email_uuid = generate_random_alias_email(scheme=2)
    assert UUID(email_uuid.split("@")[0], version=4)


def test_profile_picture_url(flask_client):
    user = create_new_user()

    assert (
        user.profile_picture_url() == f"http://{EMAIL_DOMAIN}/static/default-avatar.png"
    )


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
        reply_email="rep@sl",
        name="First Last",
    )
    assert c1.website_send_to() == f'"First Last | {prefix} at example.com" <rep@sl>'

    # empty name, ascii website_from, easy case
    c1.name = None
    c1.website_from = f"First Last <{prefix}@example.com>"
    assert c1.website_send_to() == f'"First Last | {prefix} at example.com" <rep@sl>'

    # empty name, RFC 2047 website_from
    c1.name = None
    c1.website_from = f"=?UTF-8?B?TmjGoW4gTmd1eeG7hW4=?= <{prefix}@example.com>"
    assert c1.website_send_to() == f'"Nhơn Nguyễn | {prefix} at example.com" <rep@sl>'


def test_new_addr_default_sender_format(flask_client):
    user = login(flask_client)
    alias = Alias.first()
    prefix = random_token()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{prefix}@example.com",
        reply_email="rep@sl",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == f'"First Last - {prefix} at example.com" <rep@sl>'

    # Make sure email isn't duplicated if sender name equals email
    contact.name = f"{prefix}@example.com"
    assert contact.new_addr() == f'"{prefix} at example.com" <rep@sl>'


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
        reply_email="rep@sl",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == f'"First Last - {prefix}(a)example.com" <rep@sl>'


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
        reply_email="rep@sl",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == "rep@sl"


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
        reply_email="rep@sl",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == "First Last <rep@sl>"


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
        reply_email="rep@sl",
        name="First Last",
        commit=True,
    )

    assert contact.new_addr() == f'"{prefix} at example.com" <rep@sl>'


def test_new_addr_unicode(flask_client):
    user = login(flask_client)
    alias = Alias.first()

    random_prefix = random_token()
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{random_prefix}@example.com",
        reply_email="rep@sl",
        name="Nhơn Nguyễn",
        commit=True,
    )

    assert (
        contact.new_addr()
        == f"=?utf-8?q?Nh=C6=A1n_Nguy=E1=BB=85n_-_{random_prefix}_at_example=2Ecom?= <rep@sl>"
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
    noreply_email = get_noreply_email()

    # create a contact with noreply as reply_email
    Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{random.random()}@contact.lan",
        reply_email=noreply_email,
        commit=True,
    )

    # create a contact for noreply shouldn't raise CannotCreateContactForReverseAlias
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=noreply_email,
        reply_email=generate_reply_email(noreply_email, alias),
    )
    assert contact.website_email == noreply_email


def test_user_can_send_receive():
    user = create_new_user()
    assert user.can_send_or_receive()
    user.disabled = True
    assert not user.can_send_or_receive()
    user.disabled = False
    user.delete_on = arrow.now()
    assert not user.can_send_or_receive()


def test_user_is_active():
    user = create_new_user()
    assert user.is_active()
    user.delete_on = arrow.now()
    assert not user.is_active()
    user.delete_on = arrow.now().shift(days=-10)
    assert not user.is_active()


def test_email_log_create_updates_alias_last_email_log_id(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    mailbox = Mailbox.get(alias.mailbox_id)
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=f"{random_token()}@example.com",
        reply_email=f"reply-{random_token()}@sl.local",
        commit=True,
    )

    el1 = EmailLog.create(
        contact_id=contact.id,
        user_id=user.id,
        mailbox_id=mailbox.id,
        alias_id=alias.id,
        message_id="msg1@test",
        commit=True,
    )

    Session.expire(alias)
    assert alias.last_email_log_id == el1.id

    el2 = EmailLog.create(
        contact_id=contact.id,
        user_id=user.id,
        mailbox_id=mailbox.id,
        alias_id=alias.id,
        message_id="msg2@test",
        commit=True,
    )

    Session.expire(alias)
    assert alias.last_email_log_id == el2.id


def _clear_sync_events():
    SyncEvent.filter().delete()
    Session.commit()


def test_sync_event_claim_dead_letter():
    _clear_sync_events()
    old = arrow.now().shift(minutes=-15)
    e1 = SyncEvent.create(content=b"c", created_at=old, commit=True)
    e2 = SyncEvent.create(
        content=b"c",
        created_at=old,
        taken_time=arrow.now().shift(minutes=-14),
        commit=True,
    )
    e3 = SyncEvent.create(
        content=b"c",
        created_at=old,
        taken_time=arrow.now().shift(minutes=-1),
        commit=True,
    )
    e4 = SyncEvent.create(content=b"c", created_at=arrow.now(), commit=True)
    e5 = SyncEvent.create(content=b"c", retry_count=6, created_at=old, commit=True)
    e1_id, e2_id = e1.id, e2.id
    older_than = arrow.utcnow().shift(minutes=-10)

    claimed = SyncEvent.claim_dead_letter(older_than, max_retries=5, limit=10)

    assert [e.id for e in claimed] == [e1_id, e2_id]
    for e in claimed:
        assert abs((arrow.now() - e.taken_time).total_seconds()) < 60
    # Already claimed, nothing else to claim
    assert SyncEvent.claim_dead_letter(older_than, max_retries=5, limit=10) == []
    assert e3 and e4 and e5


def test_sync_event_claim_dead_letter_respects_limit_oldest_first():
    _clear_sync_events()
    old = arrow.now().shift(minutes=-15)
    ids = [
        SyncEvent.create(content=b"c", created_at=old, commit=True).id for _ in range(4)
    ]
    older_than = arrow.utcnow().shift(minutes=-10)

    first = SyncEvent.claim_dead_letter(older_than, max_retries=5, limit=2)
    second = SyncEvent.claim_dead_letter(older_than, max_retries=5, limit=2)

    assert [e.id for e in first] == ids[:2]
    assert [e.id for e in second] == ids[2:]


def test_sync_event_claim_dead_letter_skips_locked_rows():
    from app.db import engine

    _clear_sync_events()
    old = arrow.now().shift(minutes=-15)
    ids = [
        SyncEvent.create(content=b"c", created_at=old, commit=True).id for _ in range(3)
    ]
    older_than = arrow.utcnow().shift(minutes=-10)

    conn = engine.connect()
    try:
        conn.execute("SET lock_timeout = '2s'")
        trans = conn.begin()
        conn.execute("SELECT id FROM sync_event WHERE id = %s FOR UPDATE", (ids[0],))
        claimed = SyncEvent.claim_dead_letter(older_than, max_retries=5, limit=2)
        assert [e.id for e in claimed] == ids[1:]
        trans.rollback()
    finally:
        conn.close()
