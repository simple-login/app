from typing import Optional

import arrow
import pytest

from app import mailbox_utils, config
from app.db import Session
from app.mail_sender import mail_sender
from app.models import Mailbox, MailboxActivation, User, Job
from tests.utils import create_new_user, random_email


user: Optional[User] = None


def setup_module():
    global user
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    user = create_new_user()
    user.trial_end = None
    user.lifetime = True
    Session.commit()


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False


def test_free_user_cannot_add_mailbox():
    user.lifetime = False
    email = random_email()
    try:
        with pytest.raises(mailbox_utils.OnlyPaidError):
            mailbox_utils.create_mailbox(user, email)
    finally:
        user.lifetime = True


def test_invalid_email():
    user.lifetime = True
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.create_mailbox(user, "invalid")


def test_already_used():
    user.lifetime = True
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.create_mailbox(user, user.email)


@mail_sender.store_emails_test_decorator
def test_create_mailbox():
    email = random_email()
    mailbox_utils.create_mailbox(user, email)
    mailbox = Mailbox.get_by(email=email)
    assert mailbox is not None
    assert not mailbox.verified
    activation = MailboxActivation.get_by(mailbox_id=mailbox.id)
    assert activation is not None
    assert activation.tries == 0
    assert len(activation.code) > 6

    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    mail_contents = str(mail_sent.msg)
    assert mail_contents.find(config.URL) > 0
    assert mail_contents.find(activation.code) > 0
    assert mail_sent.envelope_to == email


@mail_sender.store_emails_test_decorator
def test_create_mailbox_verified():
    email = random_email()
    output = mailbox_utils.create_mailbox(user, email, verified=True)
    assert output.mailbox is not None
    assert output.mailbox.verified
    assert output.activation is None
    mailbox = Mailbox.get_by(email=email)
    assert mailbox is not None
    assert mailbox.verified
    activation = MailboxActivation.get_by(mailbox_id=mailbox.id)
    assert activation is None

    assert 0 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_create_mailbox_with_digits():
    email = random_email()
    output = mailbox_utils.create_mailbox(
        user, email, use_digit_codes=True, send_link=False
    )
    assert output.activation is not None
    assert output.activation.tries == 0
    assert len(output.activation.code) == 6

    mailbox = Mailbox.get_by(email=email)
    assert mailbox is not None
    assert not mailbox.verified
    assert output.mailbox.id == mailbox.id

    activation = MailboxActivation.get_by(mailbox_id=mailbox.id)
    assert activation is not None
    assert output.activation.mailbox_id == activation.mailbox_id

    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    mail_contents = str(mail_sent.msg)
    assert mail_contents.find(output.activation.code) > 0
    assert mail_contents.find(config.URL) == -1
    assert mail_sent.envelope_to == email


@mail_sender.store_emails_test_decorator
def test_create_mailbox_without_verification_email():
    email = random_email()
    output = mailbox_utils.create_mailbox(
        user, email, use_digit_codes=True, send_email=False
    )
    mailbox = Mailbox.get_by(email=email)
    assert mailbox is not None
    assert not mailbox.verified
    assert mailbox.id == output.mailbox.id
    activation = MailboxActivation.get_by(mailbox_id=mailbox.id)
    assert activation is not None
    assert activation.tries == 0
    assert len(activation.code) == 6
    assert activation.code == output.activation.code

    assert 0 == len(mail_sender.get_stored_emails())


@mail_sender.store_emails_test_decorator
def test_send_verification_email():
    email = random_email()
    mailbox_utils.create_mailbox(user, email, use_digit_codes=True, send_link=False)
    mailbox = Mailbox.get_by(email=email)
    activation = MailboxActivation.get_by(mailbox_id=mailbox.id)
    mail_sender.purge_stored_emails()
    mailbox_utils.send_verification_email(user, mailbox, activation, send_link=False)

    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    mail_contents = str(mail_sent.msg)
    assert mail_contents.find(activation.code) > 0
    assert mail_contents.find(config.URL) == -1
    assert mail_sent.envelope_to == email


@mail_sender.store_emails_test_decorator
def test_send_verification_email_with_link():
    email = random_email()
    mailbox_utils.create_mailbox(user, email, use_digit_codes=True, send_link=False)
    mailbox = Mailbox.get_by(email=email)
    activation = MailboxActivation.get_by(mailbox_id=mailbox.id)
    mail_sender.purge_stored_emails()
    mailbox_utils.send_verification_email(user, mailbox, activation, send_link=True)

    assert 1 == len(mail_sender.get_stored_emails())
    mail_sent = mail_sender.get_stored_emails()[0]
    mail_contents = str(mail_sent.msg)
    assert mail_contents.find(activation.code) > 0
    assert mail_contents.find(config.URL) > -1
    assert mail_sent.envelope_to == email


def test_delete_other_user_mailbox():
    other = create_new_user()
    mailbox = Mailbox.create(user_id=other.id, email=random_email(), commit=True)
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.delete_mailbox(user, mailbox.id, transfer_mailbox_id=None)


def test_delete_default_mailbox():
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.delete_mailbox(
            user, user.default_mailbox_id, transfer_mailbox_id=None
        )


def test_transfer_to_same_mailbox():
    email = random_email()
    mailbox = mailbox_utils.create_mailbox(
        user, email, use_digit_codes=True, send_link=False
    ).mailbox
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.delete_mailbox(user, mailbox.id, transfer_mailbox_id=mailbox.id)


def test_transfer_to_other_users_mailbox():
    email = random_email()
    mailbox = mailbox_utils.create_mailbox(
        user, email, use_digit_codes=True, send_link=False
    ).mailbox
    other = create_new_user()
    other_mailbox = Mailbox.create(user_id=other.id, email=random_email(), commit=True)
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.delete_mailbox(
            user, mailbox.id, transfer_mailbox_id=other_mailbox.id
        )


def test_delete_with_no_transfer():
    email = random_email()
    mailbox = mailbox_utils.create_mailbox(
        user, email, use_digit_codes=True, send_link=False
    ).mailbox
    mailbox_utils.delete_mailbox(user, mailbox.id, transfer_mailbox_id=None)
    job = Session.query(Job).order_by(Job.id.desc()).first()
    assert job is not None
    assert job.name == config.JOB_DELETE_MAILBOX
    assert job.payload["mailbox_id"] == mailbox.id
    assert job.payload["transfer_mailbox_id"] is None


def test_delete_with_transfer():
    mailbox = mailbox_utils.create_mailbox(
        user, random_email(), use_digit_codes=True, send_link=False
    ).mailbox
    transfer_mailbox = mailbox_utils.create_mailbox(
        user, random_email(), use_digit_codes=True, send_link=False
    ).mailbox
    mailbox_utils.delete_mailbox(
        user, mailbox.id, transfer_mailbox_id=transfer_mailbox.id
    )
    job = Session.query(Job).order_by(Job.id.desc()).first()
    assert job is not None
    assert job.name == config.JOB_DELETE_MAILBOX
    assert job.payload["mailbox_id"] == mailbox.id
    assert job.payload["transfer_mailbox_id"] == transfer_mailbox.id
    mailbox_utils.delete_mailbox(user, mailbox.id, transfer_mailbox_id=None)
    job = Session.query(Job).order_by(Job.id.desc()).first()
    assert job is not None
    assert job.name == config.JOB_DELETE_MAILBOX
    assert job.payload["mailbox_id"] == mailbox.id
    assert job.payload["transfer_mailbox_id"] is None


def test_verify_non_existing_mailbox():
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.verify_mailbox_code(user, 999999999, "9999999")


def test_verify_already_verified_mailbox():
    mailbox = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, commit=True
    )
    mbox = mailbox_utils.verify_mailbox_code(user, mailbox.id, "9999999")
    assert mbox.id == mailbox.id


def test_verify_other_users_mailbox():
    other = create_new_user()
    mailbox = Mailbox.create(
        user_id=other.id, email=random_email(), verified=False, commit=True
    )
    with pytest.raises(mailbox_utils.MailboxError):
        mailbox_utils.verify_mailbox_code(user, mailbox.id, "9999999")


@mail_sender.store_emails_test_decorator
def test_verify_fail():
    output = mailbox_utils.create_mailbox(user, random_email())
    for i in range(mailbox_utils.MAX_ACTIVATION_TRIES - 1):
        try:
            mailbox_utils.verify_mailbox_code(
                user, output.mailbox.id, output.activation.code + "nop"
            )
            assert False, f"test {i}"
        except mailbox_utils.CannotVerifyError:
            activation = MailboxActivation.get_by(mailbox_id=output.mailbox.id)
            assert activation.tries == i + 1


@mail_sender.store_emails_test_decorator
def test_verify_too_may():
    output = mailbox_utils.create_mailbox(user, random_email())
    output.activation.tries = mailbox_utils.MAX_ACTIVATION_TRIES
    Session.commit()
    with pytest.raises(mailbox_utils.CannotVerifyError):
        mailbox_utils.verify_mailbox_code(
            user, output.mailbox.id, output.activation.code
        )


@mail_sender.store_emails_test_decorator
def test_verify_too_old_code():
    output = mailbox_utils.create_mailbox(user, random_email())
    output.activation.created_at = arrow.now().shift(minutes=-30)
    Session.commit()
    with pytest.raises(mailbox_utils.CannotVerifyError):
        mailbox_utils.verify_mailbox_code(
            user, output.mailbox.id, output.activation.code
        )


@mail_sender.store_emails_test_decorator
def test_verify_ok():
    output = mailbox_utils.create_mailbox(user, random_email())
    mailbox_utils.verify_mailbox_code(user, output.mailbox.id, output.activation.code)
    activation = MailboxActivation.get_by(mailbox_id=output.mailbox.id)
    assert activation is None
    mailbox = Mailbox.get(id=output.mailbox.id)
    assert mailbox.verified
