import arrow

from app import config
from app.db import Session
from app.mail_sender import mail_sender
from app.mailbox_utils import (
    create_mailbox_and_send_verification,
    verify_mailbox_with_code,
)
from app.models import Mailbox
from tests.utils import create_new_user, random_email

test_user = None


def setup_module():
    global test_user
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    test_user = create_new_user()


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False


@mail_sender.store_emails_test_decorator
def test_mailbox_creation_sends_link_verification():
    mailbox, errorMsg = create_mailbox_and_send_verification(test_user, random_email())
    assert errorMsg is None
    assert mailbox is not None
    assert mailbox.verification_code is None
    assert mailbox.verification_expiration is None
    assert mailbox.verification_tries == 0
    mails = mail_sender.get_stored_emails()
    assert len(mails) == 1
    assert "link" in str(mails[0].msg)


@mail_sender.store_emails_test_decorator
def test_mailbox_creation_sends_code_verification():
    mailbox, errorMsg = create_mailbox_and_send_verification(
        test_user, random_email(), True
    )
    assert errorMsg is None
    assert mailbox is not None
    assert mailbox.verification_code is not None
    assert mailbox.verification_expiration is not None
    assert mailbox.verification_tries == 0
    mails = mail_sender.get_stored_emails()
    assert len(mails) == 1
    assert mailbox.verification_code in str(mails[0].msg)


def test_verification_with_code():
    mailbox, errorMsg = create_mailbox_and_send_verification(
        test_user, random_email(), True
    )
    mailbox_id = mailbox.id
    assert errorMsg is None
    verified_mbox, errorMsg = verify_mailbox_with_code(
        test_user, mailbox_id, mailbox.verification_code
    )
    assert errorMsg is None
    assert verified_mbox.id == mailbox_id
    assert verified_mbox.verified
    assert verified_mbox.verification_code is None
    assert verified_mbox.verification_expiration is None
    assert verified_mbox.verification_tries == 0


def test_fail_verification_with_code():
    mailbox, errorMsg = create_mailbox_and_send_verification(
        test_user, random_email(), True
    )
    mailbox_id = mailbox.id
    assert errorMsg is None
    verified_mbox, errorMsg = verify_mailbox_with_code(test_user, mailbox_id, "INVALID")
    assert errorMsg is not None
    assert verified_mbox is None
    mbox = Mailbox.get_by(id=mailbox_id)
    assert mbox.id == mailbox_id
    assert not mbox.verified
    assert mbox.verification_code is not None
    assert mbox.verification_expiration is not None
    assert mbox.verification_tries == 1


def test_fail_verification_with_invalid_mbox_id():
    verified_mbox, errorMsg = verify_mailbox_with_code(test_user, 99999999, "INVALID")
    assert errorMsg is not None
    assert verified_mbox is None


def test_verification_with_verified_mbox_is_ok():
    mailbox, errorMsg = create_mailbox_and_send_verification(
        test_user, random_email(), True
    )
    assert errorMsg is None
    mailbox.verified = True
    Session.commit()
    verified_mbox, errorMsg = verify_mailbox_with_code(test_user, mailbox.id, "INVALID")
    assert errorMsg is None
    assert verified_mbox.id == mailbox.id


def test_try_to_validate_an_expired_code_sends_reminder():
    mailbox, errorMsg = create_mailbox_and_send_verification(
        test_user, random_email(), True
    )
    assert errorMsg is None
    mailbox.verified = True
    Session.commit()
    verified_mbox, errorMsg = verify_mailbox_with_code(test_user, mailbox.id, "INVALID")
    assert errorMsg is None
    assert verified_mbox.id == mailbox.id


@mail_sender.store_emails_test_decorator
def test_validate_expired_sends_a_new_email():
    mailbox, errorMsg = create_mailbox_and_send_verification(
        test_user, random_email(), True
    )
    assert errorMsg is None
    mailbox.verification_expiration = arrow.utcnow().shift(days=-1)
    mail_sender.purge_stored_emails()
    verified_mbox, errorMsg = verify_mailbox_with_code(
        test_user, mailbox.id, mailbox.verification_code
    )
    assert errorMsg is not None
    assert verified_mbox is None
    sent_emails = mail_sender.get_stored_emails()
    assert len(sent_emails) == 1
    assert mailbox.verification_code in str(sent_emails[0].msg)
