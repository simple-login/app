import dataclasses
import secrets
from enum import Enum
from typing import Optional

import arrow
from sqlalchemy.exc import IntegrityError

from app import config
from app.constants import JobType
from app.db import Session
from app.email_utils import (
    mailbox_already_used,
    email_can_be_used_as_mailbox_with_reason,
    send_email,
    render,
    get_email_domain_part,
)
from app.email_validation import is_valid_email
from app.log import LOG
from app.models import (
    User,
    Mailbox,
    Job,
    MailboxActivation,
    Alias,
    AliasMailbox,
    AdminAuditLog,
    AuditLogActionEnum,
)
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.abuser_audit_log_utils import emit_abuser_audit_log, AbuserAuditLogAction
from app.utils import canonicalize_email, sanitize_email


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
    email = sanitize_email(email)
    if not user.is_premium():
        LOG.i(
            f"User {user} has tried to create mailbox with {email} but is not premium"
        )
        raise OnlyPaidError()
    check_email_for_mailbox(email, user)
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


def check_email_for_mailbox(email, user):
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
    else:
        reason = email_can_be_used_as_mailbox_with_reason(email)
        if reason:
            LOG.i(
                f"User {user} has tried to create mailbox with {email} but it is invalid because {reason.value}"
            )
            raise MailboxError(f"Invalid email: {reason.value}")


def delete_mailbox(
    user: User,
    mailbox_id: int,
    transfer_mailbox_id: Optional[int],
    send_mail: bool = True,
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

    # Schedule delete mailbox job
    LOG.i(
        f"User {user} has scheduled delete mailbox job for {mailbox.id} with transfer to mailbox {transfer_mailbox_id}"
    )
    Job.create(
        name=JobType.DELETE_MAILBOX.value,
        payload={
            "mailbox_id": mailbox.id,
            "transfer_mailbox_id": transfer_mailbox_id
            if transfer_mailbox_id and transfer_mailbox_id > 0
            else None,
            "send_mail": send_mail,
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
    if mailbox.verified and not mailbox.new_email:
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
    if mailbox.new_email:
        LOG.i(
            f"User {user} has verified mailbox email change from {mailbox.email} to {mailbox.new_email}"
        )
        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.UpdateMailbox,
            message=f"Change mailbox email for mailbox {mailbox_id} (old={mailbox.email} | new={mailbox.new_email})",
        )
        mailbox.email = mailbox.new_email
        mailbox.new_email = None
        mailbox.verified = True
    elif not mailbox.verified:
        LOG.i(f"User {user} has verified mailbox {mailbox_id}")
        mailbox.verified = True
        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.VerifyMailbox,
            message=f"Verify mailbox {mailbox_id} ({mailbox.email})",
        )
        if Mailbox.get_by(email=mailbox.new_email, user_id=user.id):
            raise MailboxError("That address is already in use")

    else:
        LOG.i(
            "User {user} alread has mailbox {mailbox} verified and no pending email change"
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
    user: User,
    mailbox: Mailbox,
    activation: MailboxActivation,
    send_link: bool = True,
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


def send_change_email(user: User, mailbox: Mailbox, activation: MailboxActivation):
    verification_url = f"{config.URL}/dashboard/mailbox/confirm_change?mailbox_id={mailbox.id}&code={activation.code}"

    send_email(
        mailbox.new_email,
        "Confirm mailbox change on SimpleLogin",
        render(
            "transactional/verify-mailbox-change.txt.jinja2",
            user=user,
            link=verification_url,
            mailbox_email=mailbox.email,
            mailbox_new_email=mailbox.new_email,
        ),
        render(
            "transactional/verify-mailbox-change.html",
            user=user,
            link=verification_url,
            mailbox_email=mailbox.email,
            mailbox_new_email=mailbox.new_email,
        ),
    )


def request_mailbox_email_change(
    user: User,
    mailbox: Mailbox,
    new_email: str,
    email_ownership_verified: bool = False,
    send_email: bool = True,
    use_digit_codes: bool = False,
) -> CreateMailboxOutput:
    new_email = sanitize_email(new_email)
    if new_email == mailbox.email:
        raise MailboxError("Same email")
    check_email_for_mailbox(new_email, user)
    if email_ownership_verified:
        mailbox.email = new_email
        mailbox.new_email = None
        mailbox.verified = True
    else:
        mailbox.new_email = new_email
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.UpdateMailbox,
        message=f"Updated mailbox {mailbox.id} email ({new_email}) pre-verified({email_ownership_verified}",
    )
    try:
        Session.commit()
    except IntegrityError:
        LOG.i(f"This email {new_email} is already pending for some mailbox")
        Session.rollback()
        raise MailboxError("Email already in use")

    if email_ownership_verified:
        LOG.i(f"User {user} as created a pre-verified mailbox with {new_email}")
        return CreateMailboxOutput(mailbox=mailbox, activation=None)

    LOG.i(f"User {user} has updated mailbox email with {new_email}")
    activation = generate_activation_code(mailbox, use_digit_code=use_digit_codes)
    output = CreateMailboxOutput(mailbox=mailbox, activation=activation)

    if not send_email:
        LOG.i(f"Skipping sending validation email for mailbox {mailbox}")
        return output

    send_change_email(
        user,
        mailbox,
        activation=activation,
    )
    return output


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


def cancel_email_change(mailbox_id: int, user: User):
    mailbox = Mailbox.get(mailbox_id)
    if not mailbox:
        LOG.i(
            f"User {user} has tried to cancel a mailbox an unknown mailbox {mailbox_id}"
        )
        raise MailboxError("Invalid mailbox")
    if mailbox.user.id != user.id:
        LOG.i(
            f"User {user} has tried to cancel a mailbox {mailbox} owned by another user"
        )
        raise MailboxError("Invalid mailbox")
    mailbox.new_email = None
    LOG.i(f"User {mailbox.user} has cancelled mailbox email change")
    clear_activation_codes_for_mailbox(mailbox)


def __get_alias_mailbox_from_email(
    email_address: str, alias: Alias
) -> Optional[Mailbox]:
    for mailbox in alias.mailboxes:
        if mailbox.email == email_address:
            return mailbox

        for authorized_address in mailbox.authorized_addresses:
            if authorized_address.email == email_address:
                LOG.d(
                    "Found an authorized address for %s %s %s",
                    alias,
                    mailbox,
                    authorized_address,
                )
                return mailbox
    return None


def __get_alias_mailbox_from_email_or_canonical_email(
    email_address: str, alias: Alias
) -> Optional[Mailbox]:
    # We need to first check for the uncanonicalized version because we still have users in the db with the
    # email non canonicalized. So if it matches the already existing one use that, otherwise check the canonical one
    mbox = __get_alias_mailbox_from_email(email_address, alias)
    if mbox is not None:
        return mbox
    canonical_email = canonicalize_email(email_address)
    if canonical_email != email_address:
        return __get_alias_mailbox_from_email(canonical_email, alias)
    return None


def get_mailbox_for_reply_phase(
    envelope_mail_from: str, header_mail_from: str, alias
) -> Optional[Mailbox]:
    """return the corresponding mailbox given the mail_from and alias
    Usually the mail_from=mailbox.email but it can also be one of the authorized address
    """
    mbox = __get_alias_mailbox_from_email_or_canonical_email(envelope_mail_from, alias)
    if mbox is not None:
        return mbox
    if not header_mail_from:
        return None
    envelope_from_domain = get_email_domain_part(envelope_mail_from)
    header_from_domain = get_email_domain_part(header_mail_from)
    if envelope_from_domain != header_from_domain:
        return None
    # For services that use VERP sending (envelope from has encoded data to account for bounces)
    # if the domain is the same in the header from as the envelope from we can use the header from
    return __get_alias_mailbox_from_email_or_canonical_email(header_mail_from, alias)


def count_mailbox_aliases(mailbox: Mailbox) -> int:
    alias_ids = set()

    for am in AliasMailbox.filter_by(mailbox_id=mailbox.id).all():
        if not am.alias.is_trashed():
            alias_ids.add(am.alias_id)

    for alias in Alias.filter_by(mailbox_id=mailbox.id, delete_on=None).values(
        Alias.id
    ):
        alias_ids.add(alias.id)
    return len(alias_ids)


def admin_disable_mailbox(
    mailbox: Mailbox, admin_user: Optional[User] = None, note: Optional[str] = None
) -> int:
    """Admin-disable a mailbox. User cannot re-enable."""
    disabled = 0
    for mb in Mailbox.filter_by(email=mailbox.email).all():
        mb.flags = mb.flags | Mailbox.FLAG_ADMIN_DISABLED
        message = f"Mailbox {mb.id} ({mb.email}) admin_disabled"
        if note:
            message += f". Note: {note}"
        emit_abuser_audit_log(
            user_id=mb.user_id,
            action=AbuserAuditLogAction.Note,
            message=message,
            admin_id=admin_user.id if admin_user else None,
        )
        if admin_user:
            AdminAuditLog.create(
                admin_user_id=admin_user.id,
                action=AuditLogActionEnum.disable_mailbox.value,
                model="Mailbox",
                model_id=mb.id,
                data={},
            )
        disabled += 1

    Session.commit()

    # Send notification email
    send_admin_disable_mailbox_email(mailbox)

    return disabled


def admin_reenable_mailbox(
    mailbox: Mailbox, admin_user: Optional[User] = None, note: Optional[str] = None
) -> int:
    """Re-enable an admin-disabled mailbox."""
    enabled = 0
    for mb in Mailbox.filter_by(email=mailbox.email).all():
        mb.flags = mb.flags & ~Mailbox.FLAG_ADMIN_DISABLED
        message = f"Mailbox {mb.id} ({mb.email}) admin_reenabled"
        if note:
            message += f". Note: {note}"
        emit_abuser_audit_log(
            user_id=mb.user_id,
            action=AbuserAuditLogAction.Note,
            message=message,
            admin_id=admin_user.id if admin_user else None,
        )
        if admin_user:
            AdminAuditLog.create(
                admin_user_id=admin_user.id,
                action=AuditLogActionEnum.enable_mailbox.value,
                model="Mailbox",
                model_id=mb.id,
                data={},
            )
        enabled += 1

    Session.commit()

    # Send notification email
    send_admin_reenable_mailbox_email(mailbox)

    return enabled


def send_admin_disable_mailbox_warning_email(mailbox: Mailbox):
    """Send warning that mailbox will be admin-disabled."""
    send_email(
        mailbox.email,
        f"Action Required: Your mailbox {mailbox.email} will be disabled",
        render(
            "transactional/admin-disable-mailbox-warning.txt.jinja2",
            user=mailbox.user,
            mailbox=mailbox,
        ),
        render(
            "transactional/admin-disable-mailbox-warning.html",
            user=mailbox.user,
            mailbox=mailbox,
        ),
    )


def send_admin_disable_mailbox_email(mailbox: Mailbox):
    """Send notification that mailbox has been admin-disabled."""
    send_email(
        mailbox.email,
        f"Your mailbox {mailbox.email} has been disabled",
        render(
            "transactional/admin-disable-mailbox.txt.jinja2",
            user=mailbox.user,
            mailbox=mailbox,
        ),
        render(
            "transactional/admin-disable-mailbox.html",
            user=mailbox.user,
            mailbox=mailbox,
        ),
    )


def send_admin_reenable_mailbox_email(mailbox: Mailbox):
    """Send notification that mailbox has been re-enabled."""
    send_email(
        mailbox.email,
        f"Your mailbox {mailbox.email} has been re-enabled",
        render(
            "transactional/admin-reenable-mailbox.txt.jinja2",
            user=mailbox.user,
            mailbox=mailbox,
        ),
        render(
            "transactional/admin-reenable-mailbox.html",
            user=mailbox.user,
            mailbox=mailbox,
        ),
    )
