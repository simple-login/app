"""Matching of mailbox addresses that also covers canonical variants
(``+tag``, dots and ``googlemail.com`` for Gmail-like providers).

This module only depends on ``models`` and ``utils`` so that both
``email_utils`` and ``mailbox_utils`` can use it without import cycles.
"""

from sqlalchemy import and_, func, or_

from app.models import Mailbox, User
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


def get_equivalent_domains(email: str) -> list[str]:
    """Addresses delivering to the same inbox as `email`, its canonical form first."""
    canonical = canonicalize_email(email)
    if not canonical:
        return [sanitize_email(email)]
    local, domain = canonical.split("@")
    equivalent_domains = _EQUIVALENT_DOMAINS.get(domain, (domain,))
    return [canonical] + [f"{local}@{d}" for d in equivalent_domains if d != domain]


def equivalence_reasons(email: str, other: str) -> list[str]:
    """Rules making `email` and `other` deliver to the same inbox, empty if
    they are the same address."""
    local, _, domain = sanitize_email(email).rpartition("@")
    other_local, _, other_domain = sanitize_email(other).rpartition("@")
    reasons = []
    if domain != other_domain:
        reasons.append(f"{domain} and {other_domain} are equivalent domains")
    base, _, tag = local.partition("+")
    other_base, _, other_tag = other_local.partition("+")
    if tag != other_tag:
        reasons.append("+tag is ignored")
    if base != other_base:
        reasons.append("dots are ignored")
    return reasons


def _matches_email(column, email: str):
    """Condition matching `column` against `email` or a variant of it that
    delivers to the same inbox."""
    email = sanitize_email(email)
    conditions = [column == email]
    parts = _canonical_local_and_domain(email)
    if parts:
        local, domain = parts
        domains = _EQUIVALENT_DOMAINS[domain]
        stored_local = func.split_part(func.lower(column), "@", 1)
        stored_domain = func.split_part(func.lower(column), "@", 2)
        conditions.append(
            and_(
                stored_domain.in_(domains),
                func.replace(func.split_part(stored_local, "+", 1), ".", "") == local,
            )
        )
    return or_(*conditions)


def mailboxes_matching_email(email: str):
    """Query of all mailboxes whose address is `email` or a variant of it that
    delivers to the same inbox."""
    return Mailbox.filter(_matches_email(Mailbox.email, email))


def users_matching_email(email: str):
    """Query of all users whose email is `email` or a variant of it that
    delivers to the same inbox."""
    return User.filter(_matches_email(User.email, email))


def is_email_admin_disabled(email: str) -> bool:
    """Whether `email` (or a canonical variant of it) belongs to an admin-disabled mailbox."""
    return (
        mailboxes_matching_email(email)
        .filter(Mailbox.flags.op("&")(Mailbox.FLAG_ADMIN_DISABLED) != 0)
        .first()
        is not None
    )
