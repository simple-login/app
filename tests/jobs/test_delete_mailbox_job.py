from sqlalchemy_utils.types.arrow import arrow

from app.config import JOB_DELETE_MAILBOX
from app.db import Session
from app.mail_sender import mail_sender
from app.models import Alias, Mailbox, Job, AliasMailbox
from job_runner import delete_mailbox_job
from tests.utils import create_new_user, random_email


@mail_sender.store_emails_test_decorator
def test_delete_mailbox_transfer_mailbox_primary(flask_client):
    user = create_new_user()
    m1 = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, flush=True
    )
    m2 = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, flush=True
    )

    alias_id = Alias.create_new(user, "prefix", mailbox_id=m1.id).id
    AliasMailbox.create(alias_id=alias_id, mailbox_id=m2.id)
    job = Job.create(
        name=JOB_DELETE_MAILBOX,
        payload={"mailbox_id": m1.id, "transfer_mailbox_id": m2.id},
        run_at=arrow.now(),
        commit=True,
    )
    Session.commit()
    delete_mailbox_job(job)
    alias = Alias.get(alias_id)
    assert alias.mailbox_id == m2.id
    assert len(alias._mailboxes) == 0
    mails_sent = mail_sender.get_stored_emails()
    assert len(mails_sent) == 1
    assert str(mails_sent[0].msg).find("alias have been transferred") > -1


@mail_sender.store_emails_test_decorator
def test_delete_mailbox_transfer_mailbox_in_list(flask_client):
    user = create_new_user()
    m1 = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, flush=True
    )
    m2 = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, flush=True
    )
    m3 = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, flush=True
    )

    alias_id = Alias.create_new(user, "prefix", mailbox_id=m1.id).id
    AliasMailbox.create(alias_id=alias_id, mailbox_id=m2.id)
    job = Job.create(
        name=JOB_DELETE_MAILBOX,
        payload={"mailbox_id": m2.id, "transfer_mailbox_id": m3.id},
        run_at=arrow.now(),
        commit=True,
    )
    Session.commit()
    delete_mailbox_job(job)
    alias = Alias.get(alias_id)
    assert alias.mailbox_id == m1.id
    assert len(alias._mailboxes) == 1
    assert alias._mailboxes[0].id == m3.id
    mails_sent = mail_sender.get_stored_emails()
    assert len(mails_sent) == 1
    assert str(mails_sent[0].msg).find("alias have been transferred") > -1


@mail_sender.store_emails_test_decorator
def test_delete_mailbox_no_transfer(flask_client):
    user = create_new_user()
    m1 = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, flush=True
    )

    alias_id = Alias.create_new(user, "prefix", mailbox_id=m1.id).id
    job = Job.create(
        name=JOB_DELETE_MAILBOX,
        payload={"mailbox_id": m1.id},
        run_at=arrow.now(),
        commit=True,
    )
    Session.commit()
    delete_mailbox_job(job)
    assert Alias.get(alias_id) is None
    mails_sent = mail_sender.get_stored_emails()
    assert len(mails_sent) == 1
    assert str(mails_sent[0].msg).find("along with its aliases have been deleted") > -1
