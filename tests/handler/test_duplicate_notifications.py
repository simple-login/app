"""
Test to verify the fix for the duplicate notifications bug when sending via
Authorized Address to multiple Reverse Aliases.

Bug report (now fixed):
When a user sends an email via an Authorized Address (not Mailbox) to a
Reverse Alias, SL was triggering duplicate email notifications for every
recipient in the thread.

Example:
If an email was sent to 40 CC recipients (40 Reverse Aliases) using an
Authorized Address, SL was creating 40 identical notifications.

Fix:
Now only 1 notification is sent per mailbox per transaction.
"""

from email.message import EmailMessage

from aiosmtpd.smtp import Envelope

import email_handler
from app.config import EMAIL_DOMAIN
from app.db import Session
from app.email import headers, status
from app.mail_sender import mail_sender
from app.models import (
    Alias,
    AliasMailbox,
    AuthorizedAddress,
    Contact,
    Mailbox,
)
from app.utils import random_string
from tests.utils import create_new_user, random_email


@mail_sender.store_emails_test_decorator
def test_no_duplicate_notifications_with_authorized_address(flask_client):
    """
    Test that when sending from an authorized address to multiple reverse aliases,
    the other mailboxes receive only ONE notification, not one per reverse alias.
    """
    # Create a user with primary mailbox
    user = create_new_user()
    primary_mailbox = user.default_mailbox

    # Create a second mailbox for the user
    second_mailbox = Mailbox.create(
        user_id=user.id,
        email=f"second_{random_string(10)}@example.com",
        verified=True,
        commit=True,
    )

    # Create an alias
    alias = Alias.create_new_random(user)
    Session.flush()

    # Add the second mailbox to the alias
    AliasMailbox.create(
        alias_id=alias.id,
        mailbox_id=second_mailbox.id,
        commit=True,
    )
    Session.refresh(alias)

    # Create an authorized address for the primary mailbox
    authorized_email = f"authorized_{random_string(10)}@example.com"
    AuthorizedAddress.create(
        user_id=user.id,
        mailbox_id=primary_mailbox.id,
        email=authorized_email,
        commit=True,
    )

    # Create multiple contacts (reverse aliases) for the alias
    num_contacts = 5
    contacts = []
    for _ in range(num_contacts):
        contact = Contact.create(
            user_id=user.id,
            alias_id=alias.id,
            website_email=random_email(),
            reply_email=f"ra_{random_string(10)}@{EMAIL_DOMAIN}",
            commit=True,
        )
        contacts.append(contact)

    # Build the email message
    msg = EmailMessage()
    msg[headers.FROM] = authorized_email
    msg[headers.TO] = contacts[0].reply_email
    # Add other contacts as CC
    cc_addresses = [c.reply_email for c in contacts[1:]]
    if cc_addresses:
        msg[headers.CC] = ", ".join(cc_addresses)
    msg[headers.SUBJECT] = "Test email to multiple reverse aliases"
    msg.set_payload("Test body")

    # Build the envelope with all reverse aliases as recipients
    envelope = Envelope()
    envelope.mail_from = authorized_email
    envelope.rcpt_tos = [c.reply_email for c in contacts]

    # Send the email
    result = email_handler.handle(envelope, msg)
    assert result == status.E200

    # Check sent emails
    sent_mails = mail_sender.get_stored_emails()

    # Count emails sent to actual contacts (website emails)
    emails_to_contacts = [
        m for m in sent_mails if m.envelope_to in [c.website_email for c in contacts]
    ]

    # Count notification emails sent to the second mailbox
    notifications_to_second_mailbox = [
        m for m in sent_mails if m.envelope_to == second_mailbox.email
    ]

    # Verify that emails were sent to all contacts
    assert (
        len(emails_to_contacts) == num_contacts
    ), f"Expected {num_contacts} emails to contacts, got {len(emails_to_contacts)}"

    # With the fix: only 1 notification should be sent to the second mailbox,
    # not one per reverse alias
    assert len(notifications_to_second_mailbox) == 1, (
        f"Expected 1 notification to second mailbox, got "
        f"{len(notifications_to_second_mailbox)}. The bug may have regressed!"
    )


@mail_sender.store_emails_test_decorator
def test_no_duplicate_notifications_from_mailbox_directly(flask_client):
    """
    Test that when sending from a mailbox directly to multiple reverse aliases,
    the other mailboxes receive only ONE notification, not one per reverse alias.
    """
    # Create a user with primary mailbox
    user = create_new_user()
    primary_mailbox = user.default_mailbox

    # Create a second mailbox for the user
    second_mailbox = Mailbox.create(
        user_id=user.id,
        email=f"second_{random_string(10)}@example.com",
        verified=True,
        commit=True,
    )

    # Create an alias
    alias = Alias.create_new_random(user)
    Session.flush()

    # Add the second mailbox to the alias
    AliasMailbox.create(
        alias_id=alias.id,
        mailbox_id=second_mailbox.id,
        commit=True,
    )
    Session.refresh(alias)

    # Create multiple contacts (reverse aliases) for the alias
    num_contacts = 5
    contacts = []
    for _ in range(num_contacts):
        contact = Contact.create(
            user_id=user.id,
            alias_id=alias.id,
            website_email=random_email(),
            reply_email=f"ra_{random_string(10)}@{EMAIL_DOMAIN}",
            commit=True,
        )
        contacts.append(contact)

    # Build the email message - sending from primary mailbox directly
    msg = EmailMessage()
    msg[headers.FROM] = primary_mailbox.email
    msg[headers.TO] = contacts[0].reply_email
    cc_addresses = [c.reply_email for c in contacts[1:]]
    if cc_addresses:
        msg[headers.CC] = ", ".join(cc_addresses)
    msg[headers.SUBJECT] = "Test email to multiple reverse aliases"
    msg.set_payload("Test body")

    # Build the envelope with all reverse aliases as recipients
    envelope = Envelope()
    envelope.mail_from = primary_mailbox.email
    envelope.rcpt_tos = [c.reply_email for c in contacts]

    # Send the email
    result = email_handler.handle(envelope, msg)
    assert result == status.E200

    # Check sent emails
    sent_mails = mail_sender.get_stored_emails()

    # Count notification emails sent to the second mailbox
    notifications_to_second_mailbox = [
        m for m in sent_mails if m.envelope_to == second_mailbox.email
    ]

    # With the fix: only 1 notification should be sent to the second mailbox
    assert len(notifications_to_second_mailbox) == 1, (
        f"Expected 1 notification to second mailbox, got "
        f"{len(notifications_to_second_mailbox)}. The bug may have regressed!"
    )


@mail_sender.store_emails_test_decorator
def test_multiple_other_mailboxes_get_one_notification_each(flask_client):
    """
    Test that when an alias has multiple mailboxes and an email is sent to
    multiple reverse aliases, each non-sending mailbox receives exactly one
    notification.
    """
    # Create a user with primary mailbox
    user = create_new_user()
    primary_mailbox = user.default_mailbox

    # Create two additional mailboxes for the user
    second_mailbox = Mailbox.create(
        user_id=user.id,
        email=f"second_{random_string(10)}@example.com",
        verified=True,
        commit=True,
    )
    third_mailbox = Mailbox.create(
        user_id=user.id,
        email=f"third_{random_string(10)}@example.com",
        verified=True,
        commit=True,
    )

    # Create an alias
    alias = Alias.create_new_random(user)
    Session.flush()

    # Add both additional mailboxes to the alias
    AliasMailbox.create(
        alias_id=alias.id,
        mailbox_id=second_mailbox.id,
        commit=True,
    )
    AliasMailbox.create(
        alias_id=alias.id,
        mailbox_id=third_mailbox.id,
        commit=True,
    )
    Session.refresh(alias)

    # Create multiple contacts (reverse aliases) for the alias
    num_contacts = 3
    contacts = []
    for _ in range(num_contacts):
        contact = Contact.create(
            user_id=user.id,
            alias_id=alias.id,
            website_email=random_email(),
            reply_email=f"ra_{random_string(10)}@{EMAIL_DOMAIN}",
            commit=True,
        )
        contacts.append(contact)

    # Build the email message - sending from primary mailbox
    msg = EmailMessage()
    msg[headers.FROM] = primary_mailbox.email
    msg[headers.TO] = contacts[0].reply_email
    cc_addresses = [c.reply_email for c in contacts[1:]]
    if cc_addresses:
        msg[headers.CC] = ", ".join(cc_addresses)
    msg[headers.SUBJECT] = "Test email to multiple reverse aliases"
    msg.set_payload("Test body")

    # Build the envelope with all reverse aliases as recipients
    envelope = Envelope()
    envelope.mail_from = primary_mailbox.email
    envelope.rcpt_tos = [c.reply_email for c in contacts]

    # Send the email
    result = email_handler.handle(envelope, msg)
    assert result == status.E200

    # Check sent emails
    sent_mails = mail_sender.get_stored_emails()

    # Count notifications to each additional mailbox
    notifications_to_second = [
        m for m in sent_mails if m.envelope_to == second_mailbox.email
    ]
    notifications_to_third = [
        m for m in sent_mails if m.envelope_to == third_mailbox.email
    ]

    # Each non-sending mailbox should receive exactly one notification
    assert (
        len(notifications_to_second) == 1
    ), f"Expected 1 notification to second mailbox, got {len(notifications_to_second)}"
    assert (
        len(notifications_to_third) == 1
    ), f"Expected 1 notification to third mailbox, got {len(notifications_to_third)}"
