import random

import arrow
from aiosmtpd.smtp import Envelope

import email_handler
from app.email import status
from app.mail_sender import mail_sender
from app.models import Alias, BlockBehaviourEnum, Contact
from tests.utils import create_new_user, load_eml_file, random_email


@mail_sender.store_emails_test_decorator
def test_trash_on_forward():
    user = create_new_user()
    user.block_behaviour = BlockBehaviourEnum.return_5xx
    alias = Alias.create_new_random(user)
    alias.delete_on = arrow.utcnow().shift(days=1)
    envelope = Envelope()
    envelope.mail_from = "env.somewhere"
    envelope.rcpt_tos = [alias.email]
    original_sender_address = random_email()
    msg = load_eml_file(
        "replacement_on_forward_phase.eml",
        {
            "sender_address": original_sender_address,
            "recipient_address": alias.email,
            "cc_address": random_email(),
        },
    )
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E502


@mail_sender.store_emails_test_decorator
def test_trash_on_reply():
    user = create_new_user()
    user.block_behaviour = BlockBehaviourEnum.return_5xx
    alias = Alias.create_new_random(user)
    alias.delete_on = arrow.utcnow().shift(days=1)
    contact = Contact.create(
        user_id=alias.user.id,
        alias_id=alias.id,
        website_email=f"contact{random.random()}@mailbox.lan",
        reply_email=f"re-{random.random()}@sl.lan",
        flush=True,
    )
    envelope = Envelope()
    envelope.mail_from = "env.somewhere"
    envelope.rcpt_tos = [contact.reply_email]
    msg = load_eml_file(
        "replacement_on_reply_phase.eml",
        {
            "contact_reply_email": contact.reply_email,
            "other_contact_reply_email": random_email(),
        },
    )
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result == status.E502
