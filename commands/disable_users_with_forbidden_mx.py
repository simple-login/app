#!/usr/bin/env python3
"""
Find users and mailboxes whose email domains point to forbidden MX IPs.

This command:
1. Loads all SL domains from the public_domain table
2. Scans all users in batches of 100, checking if their email domain points to a forbidden MX IP
3. Scans all mailboxes in batches of 100, doing the same check
4. Skips emails that use SL domains
"""
import argparse
from typing import Optional, Set

import time
from sqlalchemy import func

from app.abuser import mark_user_as_abuser
from app.db import Session
from app.dns_utils import get_mx_domains, get_a_record
from app.log import LOG
from app.models import User, Mailbox, SLDomain, ForbiddenMxIp, InvalidMailboxDomain

parser = argparse.ArgumentParser(
    prog="Find users with forbidden MX",
    description="Find users and mailboxes whose email domains point to forbidden MX IPs",
)
parser.add_argument(
    "-s", "--start_user_id", default=0, type=int, help="Initial user_id"
)
parser.add_argument("-e", "--end_user_id", default=0, type=int, help="Last user_id")
parser.add_argument(
    "--start_mailbox_id", default=0, type=int, help="Initial mailbox_id"
)
parser.add_argument("--end_mailbox_id", default=0, type=int, help="Last mailbox_id")
parser.add_argument(
    "--skip-users",
    default=False,
    action="store_true",
    help="Skip user scanning",
)
parser.add_argument(
    "--skip-mailboxes",
    default=False,
    action="store_true",
    help="Skip mailbox scanning",
)
parser.add_argument(
    "--mark-abuser",
    default=False,
    action="store_true",
    help="Mark found users as abusers",
)

args = parser.parse_args()

BATCH_SIZE = 100


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


def scan_users(
    sl_domains: Set[str],
    forbidden_ips: Set[str],
    invalid_domains: Set[str],
    start_id: int,
    end_id: int,
    mark_abuser: bool,
):
    """Scan users and print those with forbidden MX IPs."""
    total = end_id - start_id
    LOG.i(f"Scanning {total} users from {start_id} to {end_id}")
    found_count = 0
    start_time = time.time()

    for batch_start in range(start_id, end_id, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, end_id)
        users = (
            User.query()
            .filter(
                User.id >= batch_start,
                User.id < batch_end,
                User.disabled == False,  # noqa: E712
            )
            .all()
        )

        for user in users:
            domain = get_domain_from_email(user.email)
            if not domain:
                continue

            # Skip SL domains
            if domain in sl_domains:
                continue

            invd = invalid_domains.intersection(domain)
            if invd:
                LOG.i(f"Found user {user} with forbidden domain {domain}")
                found_count += 1
                if mark_abuser:
                    note = f"Found forbidden domain via script: domain={domain}"
                    mark_user_as_abuser(user, note)
                    LOG.i(f"Marked user {user.id} as abuser")
                    continue

            # Check if domain has forbidden MX
            fb = check_domain_has_forbidden_mx(domain, forbidden_ips)
            if fb:
                LOG.i(f"Found user {user} with forbidden MX {domain} IP {fb}")
                found_count += 1
                if mark_abuser:
                    note = f"Found forbidden MX via script: domain={domain} forbidden_ips={fb}"
                    mark_user_as_abuser(user, note)
                    LOG.i(f"Marked user {user.id} as abuser")

        # Calculate progress and time estimation
        processed = batch_end - start_id
        remaining = end_id - batch_end
        elapsed = time.time() - start_time
        if processed > 0:
            rate = elapsed / processed
            eta_seconds = remaining * rate
            eta_hours = int(eta_seconds // 3600)
            eta_minutes = int((eta_seconds % 3600) // 60)
            LOG.i(
                f"Processed users {batch_start}-{batch_end}, "
                f"{remaining} remaining, found {found_count} so far, "
                f"ETA: {eta_hours}h {eta_minutes}m"
            )
        else:
            LOG.i(
                f"Processed users {batch_start}-{batch_end}, found {found_count} so far"
            )

    LOG.i(f"User scan complete. Found {found_count} users with forbidden MX IPs")


def scan_mailboxes(
    sl_domains: Set[str],
    forbidden_ips: Set[str],
    invalid_domains: Set[str],
    start_id: int,
    end_id: int,
    mark_abuser: bool,
):
    """Scan mailboxes and print those with forbidden MX IPs."""
    total = end_id - start_id
    LOG.i(f"Scanning {total} mailboxes from {start_id} to {end_id}")
    found_count = 0
    start_time = time.time()

    for batch_start in range(start_id, end_id, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, end_id)
        mailboxes = (
            Mailbox.query()
            .filter(Mailbox.id >= batch_start, Mailbox.id < batch_end)
            .all()
        )

        for mailbox in mailboxes:
            user = mailbox.user
            if user.disabled:
                continue
            domain = get_domain_from_email(mailbox.email)
            if not domain:
                continue

            # Skip SL domains
            if domain in sl_domains:
                continue

            invd = invalid_domains.intersection(domain)
            if invd:
                LOG.i(
                    f"Found user {user} mailbox {mailbox} with forbidden domain {domain}"
                )
                found_count += 1
                if mark_abuser and not user.disabled:
                    note = f"Found forbidden domain via script (mailbox {mailbox.id}): domain={domain}"
                    mark_user_as_abuser(user, note)
                    LOG.i(f"Marked user {user.id} as abuser")
                    continue

            # Check if domain has forbidden MX
            fb = check_domain_has_forbidden_mx(domain, forbidden_ips)
            if fb:
                LOG.i(
                    f"Found user {mailbox.user} mailbox {mailbox} with forbidden MX {domain} IPs {fb}"
                )
                found_count += 1
                if mark_abuser:
                    user = User.get(mailbox.user_id)
                    if user and not user.disabled:
                        note = f"Found forbidden MX via script (mailbox {mailbox.id}): domain={domain} forbidden_ips={fb}"
                        mark_user_as_abuser(user, note)
                        LOG.i(
                            f"Marked user {user.id} as abuser (via mailbox {mailbox.id})"
                        )

        # Calculate progress and time estimation
        processed = batch_end - start_id
        remaining = end_id - batch_end
        elapsed = time.time() - start_time
        if processed > 0:
            rate = elapsed / processed
            eta_seconds = remaining * rate
            eta_hours = int(eta_seconds // 3600)
            eta_minutes = int((eta_seconds % 3600) // 60)
            LOG.i(
                f"Processed mailboxes {batch_start}-{batch_end}, "
                f"{remaining} remaining, found {found_count} so far, "
                f"ETA: {eta_hours}h {eta_minutes}m"
            )
        else:
            LOG.i(
                f"Processed mailboxes {batch_start}-{batch_end}, found {found_count} so far"
            )

    LOG.i(f"Mailbox scan complete. Found {found_count} mailboxes with forbidden MX IPs")


def main():
    # Load SL domains and forbidden IPs
    sl_domains = load_sl_domains()
    forbidden_ips = load_forbidden_ips()
    invalid_domains = load_invalid_domains()

    if not forbidden_ips:
        LOG.w("No forbidden MX IPs configured. Nothing to check.")
        return

    if args.mark_abuser:
        LOG.i("Users will be marked as abusers when found!")
    else:
        LOG.i("Dry run mode - users will NOT be marked as abusers")

    # Scan users
    if not args.skip_users:
        user_start = args.start_user_id
        user_end = args.end_user_id
        if user_end == 0:
            user_end = Session.query(func.max(User.id)).scalar() or 0
            user_end += 1  # Include the max id

        if user_end > user_start:
            scan_users(
                sl_domains,
                forbidden_ips,
                invalid_domains,
                user_start,
                user_end,
                args.mark_abuser,
            )
        else:
            LOG.i("No users to scan")

    # Scan mailboxes
    if not args.skip_mailboxes:
        mailbox_start = args.start_mailbox_id
        mailbox_end = args.end_mailbox_id
        if mailbox_end == 0:
            mailbox_end = Session.query(func.max(Mailbox.id)).scalar() or 0
            mailbox_end += 1  # Include the max id

        if mailbox_end > mailbox_start:
            scan_mailboxes(
                sl_domains,
                forbidden_ips,
                invalid_domains,
                mailbox_start,
                mailbox_end,
                args.mark_abuser,
            )
        else:
            LOG.i("No mailboxes to scan")


if __name__ == "__main__":
    main()
