import secrets
from typing import Optional

import arrow
from itsdangerous import TimestampSigner

from app import config
from app.config import JOB_DELETE_MAILBOX
from app.db import Session
from app.email_utils import (
    is_valid_email,
    mailbox_already_used,
    email_can_be_used_as_mailbox,
    send_email,
    render,
)
from app.log import LOG
from app.models import User, Mailbox, Job

MAX_MAILBOX_VERIFICATION_TRIES = 3


class MailboxError(Exception):
    pass


def _attach_new_validation_code_for_mailbox(mailbox: Mailbox) -> Mailbox:
    mailbox.verification_code = secrets.randbelow(10**6)
    mailbox.verification_expiration = arrow.utcnow().shift(minutes=15)
    Session.commit()
    return mailbox


def _send_verification_email(user, mailbox):
    s = TimestampSigner(config.MAILBOX_SECRET)
    mailbox_id_signed = s.sign(str(mailbox.id)).decode()
    verification_url = (
        config.URL + "/dashboard/mailbox_verify" + f"?mailbox_id={mailbox_id_signed}"
    )
    send_email(
        mailbox.email,
        f"Please confirm your mailbox {mailbox.email}",
        render(
            "transactional/verify-mailbox.txt.jinja2",
            user=user,
            link=verification_url,
            mailbox=mailbox,
        ),
        render(
            "transactional/verify-mailbox.html",
            user=user,
            link=verification_url,
            mailbox=mailbox,
        ),
    )


def create_mailbox_and_send_verification(
    user: User, email: str, use_code_validation: bool = False
) -> Mailbox:
    mailbox_email = email.lower().strip().replace(" ", "")

    if not is_valid_email(mailbox_email):
        raise MailboxError(f"Invalid address {mailbox_email}")
    elif mailbox_already_used(mailbox_email, user):
        raise MailboxError(f"Mailbox {mailbox_email} already exists")
    elif not email_can_be_used_as_mailbox(mailbox_email):
        raise MailboxError(f"Invalid address {mailbox_email}")

    new_mailbox = Mailbox.create(email=mailbox_email, user_id=user.id)
    if use_code_validation:
        new_mailbox.verification_tries = 0
        new_mailbox = _attach_new_validation_code_for_mailbox(new_mailbox)
    Session.commit()
    _send_verification_email(user, new_mailbox)

    return new_mailbox


def send_new_verification_to_mailbox(user: User, mailbox: Mailbox):
    if mailbox.verified:
        return
    if mailbox.verification_tries > MAX_MAILBOX_VERIFICATION_TRIES:
        mailbox.delete()
        Session.commit()
        return
    mailbox = _attach_new_validation_code_for_mailbox(mailbox)
    Session.commit()
    _send_verification_email(user, mailbox)


def set_mailbox_verified(mailbox: Mailbox) -> Mailbox:
    mailbox.verified = True
    mailbox.verification_code = None
    mailbox.verification_expiration = None
    mailbox.verification_tries = 0
    Session.commit()
    return mailbox


def verify_mailbox_with_code(user: User, mailbox_id: int, code: str) -> Mailbox:
    mailbox = Mailbox.get_by(id=mailbox_id)
    if mailbox is None:
        raise MailboxError("Invalid mailbox")
    if mailbox.user_id != user.id:
        raise MailboxError("Invalid mailbox")
    if mailbox.verified:
        return mailbox
    if mailbox.verification_expiration < arrow.utcnow():
        mailbox = _attach_new_validation_code_for_mailbox(mailbox)
        _send_verification_email(user, mailbox)
        raise MailboxError("Code has expired. A new one has been sent")
    if mailbox.verification_code != code:
        mailbox.verification_tries += 1
        if mailbox.verification_tries >= MAX_MAILBOX_VERIFICATION_TRIES:
            mailbox.delete()
            Session.commit()
            raise MailboxError("Too many tries")
        raise MailboxError("Invalid code")

    return set_mailbox_verified(mailbox)


def delete_mailbox(
    user: User, mailbox_id: int, transfer_mailbox_id: Optional[int] = None
) -> Mailbox:
    mailbox = Mailbox.get(mailbox_id)
    if mailbox is None:
        raise MailboxError("Invalid mailbox")
    if mailbox.user_id != user.id:
        raise MailboxError("Invalid mailbox")
    if mailbox.id == user.default_mailbox_id:
        raise MailboxError("You cannot delete your default mailbox")
    if transfer_mailbox_id and transfer_mailbox_id:
        transfer_mailbox = Mailbox.get(transfer_mailbox_id)

        if not transfer_mailbox or transfer_mailbox.user_id != user.id:
            raise MailboxError("You must transfer the aliases to a mailbox you own")

        if transfer_mailbox.id == mailbox.id:
            raise MailboxError(
                "You can not transfer the aliases to the mailbox you want to delete"
            )

        if not transfer_mailbox.verified:
            raise MailboxError("Your new mailbox is not verified")
    LOG.w(
        f"Schedule delete mailbox job for {mailbox.id} with transfer to mailbox {transfer_mailbox_id}"
    )
    Job.create(
        name=JOB_DELETE_MAILBOX,
        payload={
            "mailbox_id": mailbox.id,
            "transfer_mailbox_id": transfer_mailbox_id
            if transfer_mailbox_id is not None
            else None,
        },
        run_at=arrow.now(),
        commit=True,
    )
    return mailbox
