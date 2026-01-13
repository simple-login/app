import pytest
from aiosmtpd.smtp import Envelope

import email_handler
from app.config import get_abs_path
from app.db import Session
from app.pgp_utils import load_public_key, create_pgp_context
from tests.utils import create_new_user, load_eml_file, random_email

from app.models import Alias


@pytest.fixture
def ctx():
    return create_pgp_context()


class TestEncryptWithPgp:
    """Tests for PGP encryption in email handler."""

    def test_encrypt_with_pgp_legacy(self, ctx):
        """Test PGP encryption using legacy implementation."""
        user = create_new_user()
        pgp_public_key = open(get_abs_path("local_data/public-pgp.asc")).read()
        mailbox = user.default_mailbox
        mailbox.pgp_public_key = pgp_public_key
        mailbox.generic_subject = True
        # Use force_use_rust=False to test legacy path
        mailbox.pgp_finger_print = load_public_key(
            pgp_public_key, ctx, force_use_rust=False
        )
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

    def test_encrypt_with_pgp_rust(self, ctx):
        """Test PGP encryption using Rust sl-pgp implementation."""
        user = create_new_user()
        pgp_public_key = open(get_abs_path("local_data/public-pgp.asc")).read()
        mailbox = user.default_mailbox
        mailbox.pgp_public_key = pgp_public_key
        mailbox.generic_subject = True
        # Use force_use_rust=True to test Rust path
        mailbox.pgp_finger_print = load_public_key(
            pgp_public_key, ctx, force_use_rust=True
        )
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


@pytest.mark.parametrize("use_rust", [False, True])
class TestEncryptWithPgpBoth:
    """Parametrized tests for PGP encryption with both implementations."""

    def test_encrypt_with_pgp(self, ctx, use_rust):
        user = create_new_user()
        pgp_public_key = open(get_abs_path("local_data/public-pgp.asc")).read()
        mailbox = user.default_mailbox
        mailbox.pgp_public_key = pgp_public_key
        mailbox.generic_subject = True

        # Use force_use_rust parameter to control which implementation is tested
        mailbox.pgp_finger_print = load_public_key(
            pgp_public_key, ctx, force_use_rust=use_rust
        )
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
