"""Matching of mailbox addresses that also covers canonical variants
(``+tag``, dots and ``googlemail.com`` for Gmail-like providers).

This module only depends on ``models`` and ``utils`` so that both
``email_utils`` and ``mailbox_utils`` can use it without import cycles.
"""

from sqlalchemy import and_, func, or_

from app.models import Mailbox
from app.utils import canonicalize_email, sanitize_email

# Domains delivering to the same inbox
_EQUIVALENT_DOMAINS = {
    "gmail.com": ("gmail.com", "googlemail.com"),
    "googlemail.com": ("gmail.com", "googlemail.com"),
    # Proton domains: +tag and dots are ignored, but each domain is kept separate
    "protonmail.com": ("protonmail.com",),
    "proton.me": ("proton.me",),
    "pm.me": ("pm.me",),
}


def _canonical_local_and_domain(email: str) -> tuple[str, str] | None:
    canonical = canonicalize_email(email)
    if not canonical:
        return None
    local, domain = canonical.split("@")
    if domain in _EQUIVALENT_DOMAINS:
        return local, domain
    # Not a domain that canonicalize_email normalizes: only literal matches
    return None


def mailboxes_matching_email(email: str):
    """Query of all mailboxes whose address is `email` or a variant of it that
    delivers to the same inbox."""
    email = sanitize_email(email)
    conditions = [Mailbox.email == email]
    parts = _canonical_local_and_domain(email)
    if parts:
        local, domain = parts
        domains = _EQUIVALENT_DOMAINS[domain]
        mailbox_local = func.split_part(func.lower(Mailbox.email), "@", 1)
        mailbox_domain = func.split_part(func.lower(Mailbox.email), "@", 2)
        conditions.append(
            and_(
                mailbox_domain.in_(domains),
                func.replace(func.split_part(mailbox_local, "+", 1), ".", "") == local,
            )
        )
    return Mailbox.filter(or_(*conditions))


def is_email_admin_disabled(email: str) -> bool:
    """Whether `email` (or a canonical variant of it) belongs to an admin-disabled mailbox."""
    return (
        mailboxes_matching_email(email)
        .filter(Mailbox.flags.op("&")(Mailbox.FLAG_ADMIN_DISABLED) != 0)
        .first()
        is not None
    )
