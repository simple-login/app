import pytest
from aiosmtpd.smtp import Envelope

from app.db import Session
from app.email import status
from app.models import (
    Alias,
    Contact,
    BlockBehaviourEnum,
    Mailbox,
    EmailLog,
    RefusedEmail,
)
from email_handler import MailHandler
from tests.utils import create_new_user, load_eml_file, random_email


@pytest.mark.parametrize(
    "behaviour,expected_status",
    [
        (BlockBehaviourEnum.return_2xx, status.E200),
        (BlockBehaviourEnum.return_5xx, status.E502),
    ],
)
def test_blocked_contact_behaviour(behaviour: BlockBehaviourEnum, expected_status: str):
    user = create_new_user()
    user.block_behaviour = behaviour
    alias = Alias.create_new_random(user)

    # Create a contact and block it
    contact_email = random_email()
    Contact.create(
        user_id=user.id,
        alias_id=alias.id,
        website_email=contact_email,
        reply_email=f"reply@{alias.email}",
        block_forward=True,  # Block this contact
        commit=True,
    )

    # Send an email from the blocked contact
    envelope = Envelope()
    envelope.mail_from = contact_email
    envelope.rcpt_tos = [alias.email]
    msg = load_eml_file(
        "replacement_on_forward_phase.eml",
        {
            "sender_address": contact_email,
        },
    )

    result = MailHandler()._handle(envelope, msg)

    assert result == expected_status


@pytest.mark.parametrize(
    "behaviour,expected_status",
    [
        (BlockBehaviourEnum.return_2xx, status.E200),
        (BlockBehaviourEnum.return_5xx, status.E502),
    ],
)
def test_disabled_alias_behaviour(behaviour: BlockBehaviourEnum, expected_status: str):
    user = create_new_user()
    user.block_behaviour = behaviour
    alias = Alias.create_new_random(user)
    alias.enabled = False  # Disable the alias

    # Send an email to the disabled alias
    sender_email = random_email()
    envelope = Envelope()
    envelope.mail_from = sender_email
    envelope.rcpt_tos = [alias.email]
    msg = load_eml_file(
        "replacement_on_forward_phase.eml",
        {
            "sender_address": sender_email,
        },
    )

    result = MailHandler()._handle(envelope, msg)

    assert result == expected_status


def test_admin_disabled_mailbox_behaviour():
    user = create_new_user()
    user_id = user.id
    alias = Alias.create_new_random(user)
    alias_id = alias.id
    # Disable the mailbox as an admin would do
    mailbox = user.default_mailbox
    mailbox_id = mailbox.id
    mailbox.flags = mailbox.flags | Mailbox.FLAG_ADMIN_DISABLED
    Session.flush()

    # Send an email to the disabled by admin mailbox
    sender_email = random_email()
    envelope = Envelope()
    envelope.mail_from = sender_email
    envelope.rcpt_tos = [alias.email]
    msg = load_eml_file(
        "replacement_on_forward_phase.eml",
        {
            "sender_address": sender_email,
        },
    )

    result = MailHandler()._handle(envelope, msg)
    assert result == status.E207

    el = EmailLog.filter_by(user_id=user_id).order_by(EmailLog.id.desc()).first()
    assert el.mailbox_id == mailbox_id
    assert el.alias_id == alias_id
    assert el.refused_email_id is not None
    assert not el.is_spam

    re = RefusedEmail.get(el.refused_email_id)
    assert re is not None
