#!/usr/bin/env python3
"""
Checks if the user is using a forbidden MX or domain
"""
import argparse
from typing import Optional, Set

from app.dns_utils import get_mx_domains, get_a_record
from app.log import LOG
from app.models import (
    User,
    SLDomain,
    ForbiddenMxIp,
    InvalidMailboxDomain,
    PartnerUser,
    Mailbox,
)

parser = argparse.ArgumentParser(
    prog="Find users with forbidden MX",
    description="Find users and mailboxes whose email domains point to forbidden MX IPs",
)
parser.add_argument("-u", "--user", type=str, help="User")

args = parser.parse_args()


def load_sl_domains() -> Set[str]:
    """Load all SL domains from the public_domain table."""
    sl_domains = set()
    for sl_domain in SLDomain.query().all():
        sl_domains.add(sl_domain.domain.lower())
    LOG.i(f"Loaded {len(sl_domains)} SL domains")
    return sl_domains


def load_forbidden_ips() -> Set[str]:
    """Load all forbidden MX IPs."""
    forbidden_ips = set()
    for forbidden in ForbiddenMxIp.query().all():
        forbidden_ips.add(forbidden.ip)
    LOG.i(f"Loaded {len(forbidden_ips)} forbidden MX IPs")
    return forbidden_ips


def load_invalid_domains() -> Set[str]:
    """Load all forbidden MX IPs."""
    invalid_domains = set()
    for forbidden in InvalidMailboxDomain.query().all():
        invalid_domains.add(forbidden.domain)
    LOG.i(f"Loaded {len(invalid_domains)} invalid domains")
    return invalid_domains


def get_domain_from_email(email: str) -> Optional[str]:
    """Extract domain from email address."""
    if "@" not in email:
        return None
    return email.split("@")[1].lower()


def get_mx_ips_for_domain(domain: str) -> Set[str]:
    """Get all MX IPs for a domain."""
    mx_ips = set()
    try:
        priority_domains = get_mx_domains(domain)
        for prio in priority_domains:
            for mx_domain in priority_domains[prio]:
                # Remove trailing dot if present
                mx_domain_clean = mx_domain.rstrip(".")
                a_record = get_a_record(mx_domain_clean)
                if a_record:
                    mx_ips.add(a_record)
    except Exception as e:
        LOG.d(f"Error getting MX records for {domain}: {e}")
    return mx_ips


def check_domain_has_forbidden_mx(domain: str, forbidden_ips: Set[str]) -> Set[str]:
    """Check if a domain's MX records point to any forbidden IPs."""
    mx_ips = get_mx_ips_for_domain(domain)
    return mx_ips & forbidden_ips


def check_mail(
    email: str, sl_domains: Set[str], forbidden_ips: Set[str], invalid_domains: Set[str]
) -> bool:
    domain = get_domain_from_email(email)
    if not domain:
        return False

    # Skip SL domains
    if domain in sl_domains:
        return False

    invd = invalid_domains.intersection(domain)
    if invd:
        LOG.i(f"Found email {email} with forbidden domain {domain}")
        return True

    # Check if domain has forbidden MX
    fb = check_domain_has_forbidden_mx(domain, forbidden_ips)
    if fb:
        LOG.i(f"Found email {email} with forbidden MX {domain} IP {fb}")
        return True


def find_user(email: str) -> Optional[User]:
    try:
        user_id = int(email)
        user = User.get(user_id)
        if user:
            LOG.i(f"Found user {user} with id {user_id}")
            return user
        return None
    except ValueError:
        user = User.get_by(email=email)
        if user:
            LOG.i(f"Found user {user} from mail {email}")
            return user
        pu = PartnerUser.get_by(partner_email=email)
        if pu:
            LOG.i(f"Found user {pu.user} from partner user with partner mail {email}")
            return pu.user
        mbox = Mailbox.get_by(email=email)
        if mbox:
            LOG.i(f"Found user {mbox.user} from mailbox {email}")
            return mbox.user
        return None


def main():
    # Load SL domains and forbidden IPs
    sl_domains = load_sl_domains()
    forbidden_ips = load_forbidden_ips()
    invalid_domains = load_invalid_domains()

    if not forbidden_ips:
        LOG.w("No forbidden MX IPs configured. Nothing to check.")
        return

    user_param = args.user
    if not user_param:
        LOG.i("Missing user parameter")
        return

    user = find_user(user_param)
    if not user:
        LOG.i(f"User {user_param} not found")
        return
    LOG.i(f"User {user} disabled state {user.disabled}")

    if check_mail(user.email, sl_domains, forbidden_ips, invalid_domains):
        LOG.i(f"User {user} is bad")

    for mbox in user.mailboxes():
        if check_mail(mbox.email, sl_domains, forbidden_ips, invalid_domains):
            LOG.i(f"User mailbox {mbox} is bad")


if __name__ == "__main__":
    main()
