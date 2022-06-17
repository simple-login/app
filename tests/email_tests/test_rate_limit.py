import random

from app.config import (
    MAX_ACTIVITY_DURING_MINUTE_PER_ALIAS,
    MAX_ACTIVITY_DURING_MINUTE_PER_MAILBOX,
)
from app.db import Session
from app.email.rate_limit import (
    rate_limited_forward_phase,
    rate_limited_for_alias,
    rate_limited_for_mailbox,
    rate_limited_reply_phase,
)
from app.models import Alias, EmailLog, Contact
from tests.utils import create_new_user


def test_rate_limited_forward_phase_for_alias(flask_client):
    user = create_new_user()

    # no rate limiting for a new alias
    alias = Alias.create_new_random(user)
    Session.commit()
    assert not rate_limited_for_alias(alias)

    # rate limit when there's a previous activity on alias
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
    )
    Session.commit()
    for _ in range(MAX_ACTIVITY_DURING_MINUTE_PER_ALIAS + 1):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
        )
        Session.commit()

    assert rate_limited_for_alias(alias)


def test_rate_limited_forward_phase_for_mailbox(flask_client):
    user = create_new_user()

    alias = Alias.create_new_random(user)
    Session.commit()

    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email="rep@sl.local",
    )
    Session.commit()
    for _ in range(MAX_ACTIVITY_DURING_MINUTE_PER_MAILBOX + 1):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
        )
        Session.commit()

    EmailLog.create(
        user_id=user.id,
        contact_id=contact.id,
        alias_id=contact.alias_id,
    )

    # Create another alias with the same mailbox
    # will be rate limited as there's a previous activity on mailbox
    alias2 = Alias.create_new_random(user)
    Session.commit()
    assert rate_limited_for_mailbox(alias2)


def test_rate_limited_forward_phase(flask_client):
    # no rate limiting when alias does not exist
    assert not rate_limited_forward_phase("not-exist@alias.com")


def test_rate_limited_reply_phase(flask_client):
    # no rate limiting when reply_email does not exist
    assert not rate_limited_reply_phase("not-exist-reply@alias.com")

    user = create_new_user()

    alias = Alias.create_new_random(user)
    Session.commit()

    reply_email = f"reply-{random.random()}@sl.local"
    contact = Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email="contact@example.com",
        reply_email=reply_email,
    )
    Session.commit()
    for _ in range(MAX_ACTIVITY_DURING_MINUTE_PER_ALIAS + 1):
        EmailLog.create(
            user_id=user.id,
            contact_id=contact.id,
            alias_id=contact.alias_id,
        )
        Session.commit()

    assert rate_limited_reply_phase(reply_email)
