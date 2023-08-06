from aiosmtpd.smtp import Envelope

import email_handler
from app.config import get_abs_path
from app.db import Session
from app.pgp_utils import load_public_key
from tests.utils import create_new_user, load_eml_file, random_email

from app.models import Alias


def test_encrypt_with_pgp():
    user = create_new_user()
    pgp_public_key = open(get_abs_path("local_data/public-pgp.asc")).read()
    mailbox = user.default_mailbox
    mailbox.pgp_public_key = pgp_public_key
    mailbox.generic_subject = True
    mailbox.pgp_finger_print = load_public_key(pgp_public_key)
    alias = Alias.create_new_random(user)
    Session.flush()
    sender_address = random_email()
    msg = load_eml_file(
        "email_to_pgp_encrypt.eml",
        {
            "sender_address": sender_address,
            "recipient_address": alias.email,
        },
    )
    envelope = Envelope()
    envelope.mail_from = sender_address
    envelope.rcpt_tos = [alias.email]
    result = email_handler.MailHandler()._handle(envelope, msg)
    assert result is not None
