import arrow
import pytest
from sqlalchemy import desc

from app import config
from app.config import JOB_DELETE_MAILBOX
from app.db import Session
from app.mail_sender import mail_sender
from app.mailbox_utils import (
    create_mailbox_and_send_verification,
    verify_mailbox_with_code,
    MailboxError,
    delete_mailbox,
)
from app.models import Mailbox, Job
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
    mailbox = create_mailbox_and_send_verification(test_user, random_email())
    assert mailbox is not None
    assert mailbox.verification_code is None
    assert mailbox.verification_expiration is None
    assert mailbox.verification_tries == 0
    mails = mail_sender.get_stored_emails()
    assert len(mails) == 1
    assert "link" in str(mails[0].msg)


@mail_sender.store_emails_test_decorator
def test_mailbox_creation_sends_code_verification():
    mailbox = create_mailbox_and_send_verification(test_user, random_email(), True)
    assert mailbox is not None
    assert mailbox.verification_code is not None
    assert mailbox.verification_expiration is not None
    assert mailbox.verification_tries == 0
    mails = mail_sender.get_stored_emails()
    assert len(mails) == 1
    assert mailbox.verification_code in str(mails[0].msg)


def test_verification_with_code():
    mailbox = create_mailbox_and_send_verification(test_user, random_email(), True)
    mailbox_id = mailbox.id
    verified_mbox = verify_mailbox_with_code(
        test_user, mailbox_id, mailbox.verification_code
    )
    assert verified_mbox.id == mailbox_id
    assert verified_mbox.verified
    assert verified_mbox.verification_code is None
    assert verified_mbox.verification_expiration is None
    assert verified_mbox.verification_tries == 0


def test_fail_verification_with_code():
    mailbox = create_mailbox_and_send_verification(test_user, random_email(), True)
    mailbox_id = mailbox.id
    with pytest.raises(MailboxError):
        verify_mailbox_with_code(test_user, mailbox_id, "INVALID")
    mbox = Mailbox.get_by(id=mailbox_id)
    assert mbox.id == mailbox_id
    assert not mbox.verified
    assert mbox.verification_code is not None
    assert mbox.verification_expiration is not None
    assert mbox.verification_tries == 1


def test_fail_verification_with_invalid_mbox_id():
    with pytest.raises(MailboxError):
        verify_mailbox_with_code(test_user, 99999999, "INVALID")


def test_verification_with_verified_mbox_is_ok():
    mailbox = Mailbox.create(email=random_email(), user_id=test_user.id, verified=True)
    Session.commit()
    verified_mbox = verify_mailbox_with_code(test_user, mailbox.id, "INVALID")
    assert verified_mbox.id == mailbox.id


@mail_sender.store_emails_test_decorator
def test_validate_expired_sends_a_new_email():
    mailbox = Mailbox.create(
        email=random_email(),
        user_id=test_user.id,
        verification_expiration=arrow.utcnow().shift(days=-1),
    )
    Session.commit()
    with pytest.raises(MailboxError):
        verify_mailbox_with_code(test_user, mailbox.id, mailbox.verification_code)
    sent_emails = mail_sender.get_stored_emails()
    assert len(sent_emails) == 1
    assert mailbox.verification_code in str(sent_emails[0].msg)


def test_delete_mailbox_without_transfer():
    mailbox = Mailbox.create(email=random_email(), user_id=test_user.id, verified=True)
    Session.commit()
    delete_mailbox(test_user, mailbox.id)
    job = (
        Session.query(Job)
        .filter_by(name=JOB_DELETE_MAILBOX)
        .order_by(desc(Job.id))
        .first()
    )
    assert job.payload["mailbox_id"] == mailbox.id
    assert job.payload["transfer_mailbox_id"] is None


def test_delete_mailbox_with_transfer():
    mailbox = Mailbox.create(email=random_email(), user_id=test_user.id, verified=True)
    transfer_mailbox = Mailbox.create(
        email=random_email(), user_id=test_user.id, verified=True
    )
    Session.commit()
    delete_mailbox(test_user, mailbox.id, transfer_mailbox.id)
    job = (
        Session.query(Job)
        .filter_by(name=JOB_DELETE_MAILBOX)
        .order_by(desc(Job.id))
        .first()
    )
    assert job.payload["mailbox_id"] == mailbox.id
    assert job.payload["transfer_mailbox_id"] == transfer_mailbox.id


def test_cannot_delete_primary_mailbox():
    with pytest.raises(MailboxError):
        delete_mailbox(test_user, test_user.default_mailbox_id)


def test_cannot_delete_another_users_mailbox():
    other_user = create_new_user()
    mailbox = Mailbox.create(email=random_email(), user_id=test_user.id, verified=True)
    with pytest.raises(MailboxError):
        delete_mailbox(other_user, mailbox.id)


def test_cannot_delete_transfer_being_the_same():
    mailbox = Mailbox.create(email=random_email(), user_id=test_user.id, verified=True)
    with pytest.raises(MailboxError):
        delete_mailbox(test_user, mailbox.id, mailbox.id)


def test_cannot_transfer_to_another_user_mailbox():
    other_user = create_new_user()
    mailbox = Mailbox.create(email=random_email(), user_id=test_user.id, verified=True)
    transfer_mailbox = Mailbox.create(
        email=random_email(), user_id=other_user.id, verified=True
    )
    Session.commit()
    with pytest.raises(MailboxError):
        delete_mailbox(test_user, mailbox.id, transfer_mailbox.id)
