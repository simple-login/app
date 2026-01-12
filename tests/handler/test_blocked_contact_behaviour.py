import pytest
from aiosmtpd.smtp import Envelope

from email_handler import MailHandler
from app.models import Alias, Contact, BlockBehaviourEnum
from app.email import status
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
