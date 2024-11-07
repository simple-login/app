import dataclasses
import secrets
from enum import Enum
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
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


@dataclasses.dataclass
class CreateMailboxOutput:
    mailbox: Mailbox
    activation: Optional[MailboxActivation]


class MailboxError(Exception):
    def __init__(self, msg: str):
        self.msg = msg


class OnlyPaidError(MailboxError):
    def __init__(self):
        self.msg = "Only available for paid plans"


class CannotVerifyError(MailboxError):
    def __init__(self, msg: str, deleted_activation_code: bool = False):
        self.msg = msg
        self.deleted_activation_code = deleted_activation_code


MAX_ACTIVATION_TRIES = 3


def create_mailbox(
    user: User,
    email: str,
    verified: bool = False,
    send_email: bool = True,
    use_digit_codes: bool = False,
    send_link: bool = True,
) -> CreateMailboxOutput:
    if not user.is_premium():
        LOG.i(
            f"User {user} has tried to create mailbox with {email} but is not premium"
        )
        raise OnlyPaidError()
    if not is_valid_email(email):
        LOG.i(
            f"User {user} has tried to create mailbox with {email} but is not valid email"
        )
        raise MailboxError("Invalid email")
    elif mailbox_already_used(email, user):
        LOG.i(
            f"User {user} has tried to create mailbox with {email} but email is already used"
        )
        raise MailboxError("Email already used")
    elif not email_can_be_used_as_mailbox(email):
        LOG.i(
            f"User {user} has tried to create mailbox with {email} but email is invalid"
        )
        raise MailboxError("Invalid email")
    new_mailbox: Mailbox = Mailbox.create(
        email=email, user_id=user.id, verified=verified, commit=True
    )
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.CreateMailbox,
        message=f"Create mailbox {new_mailbox.id} ({new_mailbox.email}). Verified={verified}",
        commit=True,
    )

    if verified:
        LOG.i(f"User {user} as created a pre-verified mailbox with {email}")
        return CreateMailboxOutput(mailbox=new_mailbox, activation=None)

    LOG.i(f"User {user} has created mailbox with {email}")
    activation = generate_activation_code(new_mailbox, use_digit_code=use_digit_codes)
    output = CreateMailboxOutput(mailbox=new_mailbox, activation=activation)

    if not send_email:
        LOG.i(f"Skipping sending validation email for mailbox {new_mailbox}")
        return output

    send_verification_email(
        user,
        new_mailbox,
        activation=activation,
        send_link=send_link,
    )
    return output


def delete_mailbox(
    user: User, mailbox_id: int, transfer_mailbox_id: Optional[int]
) -> Mailbox:
    mailbox = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        LOG.i(
            f"User {user} has tried to delete another user's mailbox with {mailbox_id}"
        )
        raise MailboxError("Invalid mailbox")

    if mailbox.id == user.default_mailbox_id:
        LOG.i(f"User {user} has tried to delete the default mailbox")
        raise MailboxError("Cannot delete your default mailbox")

    if transfer_mailbox_id and transfer_mailbox_id > 0:
        transfer_mailbox = Mailbox.get(transfer_mailbox_id)

        if not transfer_mailbox or transfer_mailbox.user_id != user.id:
            LOG.i(
                f"User {user} has tried to transfer to a mailbox owned by another user"
            )
            raise MailboxError("You must transfer the aliases to a mailbox you own")

        if transfer_mailbox.id == mailbox.id:
            LOG.i(
                f"User {user} has tried to transfer to the same mailbox he is deleting"
            )
            raise MailboxError(
                "You can not transfer the aliases to the mailbox you want to delete"
            )

        if not transfer_mailbox.verified:
            LOG.i(f"User {user} has tried to transfer to a non verified mailbox")
            raise MailboxError("Your new mailbox is not verified")

    # Schedule delete account job
    LOG.i(
        f"User {user} has scheduled delete mailbox job for {mailbox.id} with transfer to mailbox {transfer_mailbox_id}"
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


def clear_activation_codes_for_mailbox(mailbox: Mailbox):
    Session.query(MailboxActivation).filter(
        MailboxActivation.mailbox_id == mailbox.id
    ).delete()
    Session.commit()


def verify_mailbox_code(user: User, mailbox_id: int, code: str) -> Mailbox:
    mailbox = Mailbox.get(mailbox_id)
    if not mailbox:
        LOG.i(
            f"User {user} failed to verify mailbox {mailbox_id} because it does not exist"
        )
        raise MailboxError("Invalid mailbox")
    if mailbox.user_id != user.id:
        LOG.i(
            f"User {user} failed to verify mailbox {mailbox_id} because it's owned by another user"
        )
        raise MailboxError("Invalid mailbox")
    if mailbox.verified:
        LOG.i(
            f"User {user} failed to verify mailbox {mailbox_id} because it's already verified"
        )
        clear_activation_codes_for_mailbox(mailbox)
        return mailbox

    activation = (
        MailboxActivation.filter(MailboxActivation.mailbox_id == mailbox_id)
        .order_by(MailboxActivation.created_at.desc())
        .first()
    )
    if not activation:
        LOG.i(
            f"User {user} failed to verify mailbox {mailbox_id} because there is no activation"
        )
        raise MailboxError("Invalid code")
    if activation.tries >= MAX_ACTIVATION_TRIES:
        LOG.i(f"User {user} failed to verify mailbox {mailbox_id} more than 3 times")
        clear_activation_codes_for_mailbox(mailbox)
        raise CannotVerifyError(
            "Invalid activation code. Please request another code.",
            deleted_activation_code=True,
        )
    if activation.created_at < arrow.now().shift(minutes=-15):
        LOG.i(
            f"User {user} failed to verify mailbox {mailbox_id} because code is too old"
        )
        clear_activation_codes_for_mailbox(mailbox)
        raise CannotVerifyError("Invalid activation code. Please request another code.")
    if code != activation.code:
        LOG.i(
            f"User {user} failed to verify mailbox {mailbox_id} because code does not match"
        )
        activation.tries = activation.tries + 1
        Session.commit()
        raise CannotVerifyError("Invalid activation code")
    LOG.i(f"User {user} has verified mailbox {mailbox_id}")
    mailbox.verified = True
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.VerifyMailbox,
        message=f"Verify mailbox {mailbox_id} ({mailbox.email})",
    )
    clear_activation_codes_for_mailbox(mailbox)
    return mailbox


def generate_activation_code(
    mailbox: Mailbox, use_digit_code: bool = False
) -> MailboxActivation:
    clear_activation_codes_for_mailbox(mailbox)
    if use_digit_code:
        if config.MAILBOX_VERIFICATION_OVERRIDE_CODE:
            code = config.MAILBOX_VERIFICATION_OVERRIDE_CODE
        else:
            code = "{:06d}".format(secrets.randbelow(1000000))[:6]
    else:
        code = secrets.token_urlsafe(16)
    return MailboxActivation.create(
        mailbox_id=mailbox.id,
        code=code,
        tries=0,
        commit=True,
    )


def send_verification_email(
    user: User, mailbox: Mailbox, activation: MailboxActivation, send_link: bool = True
):
    LOG.i(
        f"Sending mailbox verification email to {mailbox.email} with send link={send_link}"
    )

    if send_link:
        verification_url = (
            config.URL
            + "/dashboard/mailbox_verify"
            + f"?mailbox_id={mailbox.id}&code={activation.code}"
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


class MailboxEmailChangeError(Enum):
    InvalidId = 1
    EmailAlreadyUsed = 2


@dataclasses.dataclass
class MailboxEmailChangeResult:
    error: Optional[MailboxEmailChangeError]
    message: str
    message_category: str


def perform_mailbox_email_change(mailbox_id: int) -> MailboxEmailChangeResult:
    mailbox: Optional[Mailbox] = Mailbox.get(mailbox_id)

    # new_email can be None if user cancels change in the meantime
    if mailbox and mailbox.new_email:
        user = mailbox.user
        if Mailbox.get_by(email=mailbox.new_email, user_id=user.id):
            return MailboxEmailChangeResult(
                error=MailboxEmailChangeError.EmailAlreadyUsed,
                message=f"{mailbox.new_email} is already used",
                message_category="error",
            )

        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.UpdateMailbox,
            message=f"Change mailbox email for mailbox {mailbox_id} (old={mailbox.email} | new={mailbox.new_email})",
        )
        mailbox.email = mailbox.new_email
        mailbox.new_email = None

        # mark mailbox as verified if the change request is sent from an unverified mailbox
        mailbox.verified = True
        Session.commit()

        LOG.d("Mailbox change %s is verified", mailbox)
        return MailboxEmailChangeResult(
            error=None,
            message=f"The {mailbox.email} is updated",
            message_category="success",
        )
    else:
        return MailboxEmailChangeResult(
            error=MailboxEmailChangeError.InvalidId,
            message="Invalid link",
            message_category="error",
        )
