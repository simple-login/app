import re

from dataclasses import dataclass
from typing import Optional

from app.db import Session
from app.email_utils import get_email_domain_part
from app.log import LOG
from app.models import User, CustomDomain, SLDomain, Mailbox

_ALLOWED_DOMAIN_REGEX = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


@dataclass
class CreateCustomDomainResult:
    message: str = ""
    message_category: str = ""
    success: bool = False
    instance: Optional[CustomDomain] = None
    redirect: Optional[str] = None


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


def can_domain_be_used(user: User, domain: str) -> Optional[str]:
    if not is_valid_domain(domain):
        return "This is not a valid domain"
    elif SLDomain.get_by(domain=domain):
        return "A custom domain cannot be a built-in domain."
    elif CustomDomain.get_by(domain=domain):
        return f"{domain} already used"
    elif get_email_domain_part(user.email) == domain:
        return "You cannot add a domain that you are currently using for your personal email. Please change your personal email to your real email"
    elif Mailbox.filter(
        Mailbox.verified.is_(True), Mailbox.email.endswith(f"@{domain}")
    ).first():
        return f"{domain} already used in a SimpleLogin mailbox"
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
    can_use_domain_error = can_domain_be_used(user, new_domain)
    if can_use_domain_error:
        return CreateCustomDomainResult(
            message=can_use_domain_error, message_category="error"
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

    Session.commit()

    return CreateCustomDomainResult(
        success=True,
        instance=new_custom_domain,
    )
