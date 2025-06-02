import arrow
import re

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from app.constants import JobType
from app.db import Session
from app.email_utils import get_email_domain_part
from app.log import LOG
from app.models import User, CustomDomain, SLDomain, Mailbox, Job, DomainMailbox, Alias
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction

_ALLOWED_DOMAIN_REGEX = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
_MAX_MAILBOXES_PER_DOMAIN = 20


@dataclass
class CreateCustomDomainResult:
    message: str = ""
    message_category: str = ""
    success: bool = False
    instance: Optional[CustomDomain] = None
    redirect: Optional[str] = None


class CannotUseDomainReason(Enum):
    InvalidDomain = 1
    BuiltinDomain = 2
    DomainAlreadyUsed = 3
    DomainPartOfUserEmail = 4
    DomainUserInMailbox = 5

    def message(self, domain: str) -> str:
        if self == CannotUseDomainReason.InvalidDomain:
            return "This is not a valid domain"
        elif self == CannotUseDomainReason.BuiltinDomain:
            return "A custom domain cannot be a built-in domain."
        elif self == CannotUseDomainReason.DomainAlreadyUsed:
            return f"{domain} already used"
        elif self == CannotUseDomainReason.DomainPartOfUserEmail:
            return "You cannot add a domain that you are currently using for your personal email. Please change your personal email to your real email"
        elif self == CannotUseDomainReason.DomainUserInMailbox:
            return f"{domain} already used in a SimpleLogin mailbox"
        else:
            raise Exception("Invalid CannotUseDomainReason")


class CannotSetCustomDomainMailboxesCause(Enum):
    InvalidMailbox = "Something went wrong, please retry"
    NoMailboxes = "You must select at least 1 mailbox"
    TooManyMailboxes = (
        f"You can only set up to {_MAX_MAILBOXES_PER_DOMAIN} mailboxes per domain"
    )


@dataclass
class SetCustomDomainMailboxesResult:
    success: bool
    reason: Optional[CannotSetCustomDomainMailboxesCause] = None


def is_valid_domain(domain: str) -> bool:
    """
    Checks that a domain is valid according to RFC 1035
    """
    if len(domain) > 255:
        return False
    if domain.endswith("."):
        domain = domain[:-1]  # Strip the trailing dot
    labels = domain.split(".")
    if not labels:
        return False
    for label in labels:
        if not _ALLOWED_DOMAIN_REGEX.match(label):
            return False
    return True


def sanitize_domain(domain: str) -> str:
    new_domain = domain.lower().strip()
    if new_domain.startswith("http://"):
        new_domain = new_domain[len("http://") :]

    if new_domain.startswith("https://"):
        new_domain = new_domain[len("https://") :]

    return new_domain


def can_domain_be_used(user: User, domain: str) -> Optional[CannotUseDomainReason]:
    if not is_valid_domain(domain):
        return CannotUseDomainReason.InvalidDomain
    elif SLDomain.get_by(domain=domain):
        return CannotUseDomainReason.BuiltinDomain
    elif CustomDomain.get_by(domain=domain):
        return CannotUseDomainReason.DomainAlreadyUsed
    elif get_email_domain_part(user.email) == domain:
        return CannotUseDomainReason.DomainPartOfUserEmail
    elif Mailbox.filter(
        Mailbox.verified.is_(True), Mailbox.email.endswith(f"@{domain}")
    ).first():
        return CannotUseDomainReason.DomainUserInMailbox
    else:
        return None


def create_custom_domain(
    user: User, domain: str, partner_id: Optional[int] = None
) -> CreateCustomDomainResult:
    if not user.is_premium():
        return CreateCustomDomainResult(
            message="Only premium plan can add custom domain",
            message_category="warning",
        )

    new_domain = sanitize_domain(domain)
    domain_forbidden_cause = can_domain_be_used(user, new_domain)
    if domain_forbidden_cause:
        return CreateCustomDomainResult(
            message=domain_forbidden_cause.message(new_domain), message_category="error"
        )

    new_custom_domain = CustomDomain.create(domain=new_domain, user_id=user.id)

    # new domain has ownership verified if its parent has the ownership verified
    for root_cd in user.custom_domains:
        if new_domain.endswith("." + root_cd.domain) and root_cd.ownership_verified:
            LOG.i(
                "%s ownership verified thanks to %s",
                new_custom_domain,
                root_cd,
            )
            new_custom_domain.ownership_verified = True

    # Add the partner_id in case it's passed
    if partner_id is not None:
        new_custom_domain.partner_id = partner_id

    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.CreateCustomDomain,
        message=f"Created custom domain {new_custom_domain.id} ({new_domain})",
    )
    Session.commit()

    return CreateCustomDomainResult(
        success=True,
        instance=new_custom_domain,
    )


def delete_custom_domain(domain: CustomDomain):
    # Schedule delete domain job
    LOG.w("schedule delete domain job for %s", domain)
    domain.pending_deletion = True
    Job.create(
        name=JobType.DELETE_DOMAIN.value,
        payload={"custom_domain_id": domain.id},
        run_at=arrow.now(),
        commit=True,
    )


def set_custom_domain_mailboxes(
    user_id: int, custom_domain: CustomDomain, mailbox_ids: List[int]
) -> SetCustomDomainMailboxesResult:
    if len(mailbox_ids) == 0:
        return SetCustomDomainMailboxesResult(
            success=False, reason=CannotSetCustomDomainMailboxesCause.NoMailboxes
        )
    elif len(mailbox_ids) > _MAX_MAILBOXES_PER_DOMAIN:
        return SetCustomDomainMailboxesResult(
            success=False, reason=CannotSetCustomDomainMailboxesCause.TooManyMailboxes
        )

    mailboxes = (
        Session.query(Mailbox)
        .filter(
            Mailbox.id.in_(mailbox_ids),
            Mailbox.user_id == user_id,
            Mailbox.verified == True,  # noqa: E712
        )
        .all()
    )
    if len(mailboxes) != len(mailbox_ids):
        return SetCustomDomainMailboxesResult(
            success=False, reason=CannotSetCustomDomainMailboxesCause.InvalidMailbox
        )

    # first remove all existing domain-mailboxes links
    DomainMailbox.filter_by(domain_id=custom_domain.id).delete()
    Session.flush()

    for mailbox in mailboxes:
        DomainMailbox.create(domain_id=custom_domain.id, mailbox_id=mailbox.id)

    mailboxes_as_str = ",".join(map(str, mailbox_ids))
    emit_user_audit_log(
        user=custom_domain.user,
        action=UserAuditLogAction.UpdateCustomDomain,
        message=f"Updated custom domain {custom_domain.id} mailboxes (domain={custom_domain.domain}) (mailboxes={mailboxes_as_str})",
    )
    Session.commit()
    return SetCustomDomainMailboxesResult(success=True)


def count_custom_domain_aliases(custom_domain: CustomDomain) -> int:
    return Alias.filter_by(custom_domain_id=custom_domain.id, delete_on=None).count()
