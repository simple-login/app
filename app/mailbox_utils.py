import secrets
import random
from typing import Optional
import arrow

from app import config
from app.config import JOB_DELETE_MAILBOX
from app.db import Session
from app.email_utils import (
    mailbox_already_used,
    email_can_be_used_as_mailbox,
    send_email,
    render,
)
from app.email_validation import is_valid_email
from app.log import LOG
from app.models import User, Mailbox, Job, MailboxActivation


class MailboxError(Exception):
    def __init__(self, msg: str):
        self.msg = msg


def create_mailbox(
    user: User,
    email: str,
    use_digit_codes: bool = False,
    send_verification_link: bool = True,
) -> Mailbox:
    if not user.is_premium():
        raise MailboxError("Only premium plan can add additional mailbox")
    if not is_valid_email(email):
        raise MailboxError("Invalid email")
    elif mailbox_already_used(email, user):
        raise MailboxError("Email already used")
    elif not email_can_be_used_as_mailbox(email):
        raise MailboxError("Invalid email")
    new_mailbox = Mailbox.create(email=email, user_id=user.id, commit=True)

    send_verification_email(
        user,
        new_mailbox,
        use_digit_code=use_digit_codes,
        send_link=send_verification_link,
    )
    return new_mailbox


def delete_mailbox(
    user: User, mailbox_id: int, transfer_mailbox_id: Optional[int]
) -> Mailbox:
    mailbox = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        raise MailboxError("Invalid mailbox")

    if mailbox.id == user.default_mailbox_id:
        raise MailboxError("Cannot delete your default mailbox")

    if transfer_mailbox_id and transfer_mailbox_id > 0:
        transfer_mailbox = Mailbox.get(transfer_mailbox_id)

        if not transfer_mailbox or transfer_mailbox.user_id != user.id:
            raise MailboxError("You must transfer the aliases to a mailbox you own")

        if transfer_mailbox.id == mailbox.id:
            raise MailboxError(
                "You can not transfer the aliases to the mailbox you want to delete"
            )

        if not transfer_mailbox.verified:
            MailboxError("Your new mailbox is not verified")

    # Schedule delete account job
    LOG.w(
        f"schedule delete mailbox job for {mailbox.id} with transfer to mailbox {transfer_mailbox_id}"
    )
    Job.create(
        name=JOB_DELETE_MAILBOX,
        payload={
            "mailbox_id": mailbox.id,
            "transfer_mailbox_id": transfer_mailbox_id
            if transfer_mailbox_id and transfer_mailbox_id > 0
            else None,
        },
        run_at=arrow.now(),
        commit=True,
    )
    return mailbox


def set_default_mailbox(user: User, mailbox_id: int) -> Mailbox:
    mailbox = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        raise MailboxError("Invalid mailbox")

    if not mailbox.verified:
        raise MailboxError("This is mailbox is not verified")

    if mailbox.id == user.default_mailbox_id:
        return mailbox

    user.default_mailbox_id = mailbox.id
    Session.commit()
    return mailbox


def clear_activation_codes_for_mailbox(mailbox: Mailbox):
    Session.query(MailboxActivation).filter(
        MailboxActivation.mailbox_id == mailbox.id
    ).delete()
    Session.commit()


def verify_mailbox_code(mailbox_id: int, code: str) -> Mailbox:
    mailbox = Mailbox.get(mailbox_id)
    if not mailbox:
        raise MailboxError("Invalid mailbox")
    if mailbox.verified:
        clear_activation_codes_for_mailbox(mailbox)
        return mailbox
    activation = MailboxActivation.get_by(mailbox_id=mailbox_id).first()
    if not activation:
        raise MailboxError("Invalid code")
    if activation.tries > 3:
        clear_activation_codes_for_mailbox(mailbox)
        raise MailboxError("Invalid activation code. Please request another code.")
    if activation.created_at < arrow.now().shift(minutes=-15):
        clear_activation_codes_for_mailbox(mailbox)
        raise MailboxError("Invalid activation code. Please request another code.")
    if code != activation.code:
        activation.tries = activation.tries + 1
        Session.commit()
        raise MailboxError("Invalid activation code")
    mailbox.verified = True
    clear_activation_codes_for_mailbox(mailbox)
    return mailbox


def send_verification_email(
    user: User, mailbox: Mailbox, use_digit_code: bool = False, send_link: bool = True
):
    clear_activation_codes_for_mailbox(mailbox)
    if use_digit_code:
        code = "{:06d}".format(random.randint(1, 999999))
    else:
        code = secrets.token_urlsafe(16)
    activation = MailboxActivation.create(
        mailbox_id=mailbox.id,
        code=code,
        tries=0,
    )
    Session.commit()

    if send_link:
        verification_url = (
            config.URL
            + "/dashboard/mailbox_verify"
            + f"?mailbox_id={mailbox.id}&code={code}"
        )
    else:
        verification_url = None

    send_email(
        mailbox.email,
        f"Please confirm your mailbox {mailbox.email}",
        render(
            "transactional/verify-mailbox.txt.jinja2",
            user=user,
            code=activation.code,
            link=verification_url,
            mailbox_email=mailbox.email,
        ),
        render(
            "transactional/verify-mailbox.html",
            user=user,
            code=activation.code,
            link=verification_url,
            mailbox_email=mailbox.email,
        ),
    )
