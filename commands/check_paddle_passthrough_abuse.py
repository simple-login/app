#!/usr/bin/env python3
"""
Look for Paddle subscriptions that may have been taken over through the
passthrough field.

Before the fix, the /paddle "subscription_created" callback credited whichever
account the (browser-controlled) passthrough named, so anybody able to complete
a checkout could overwrite the subscription row of another user. The overwrite
is not silent: it emits a `subscription_extended` entry on the victim.

A legitimate extension can only happen when the user is able to reach the
pricing page, which requires their subscription to be cancelled or lapsed. So
an extension that lands while the subscription could not have lapsed yet, with
no cancellation before it, is the fingerprint of a takeover.

Usage
-----
    # report the suspicious extensions (read-only)
    python -m commands.check_paddle_passthrough_abuse

    # every extension with no cancellation before it, for exhaustive triage
    python -m commands.check_paddle_passthrough_abuse --all-extensions

    # ask Paddle who actually paid for the subscription now held by each
    # reported user, to compare with the account email
    python -m commands.check_paddle_passthrough_abuse --paddle

This command only reports: repairing a subscription means moving it back in
Paddle, which has to be done by hand.
"""

import argparse
import sys
from typing import List, Optional

import requests

from app.config import PADDLE_AUTH_CODE, PADDLE_VENDOR_ID
from app.db import Session
from app.models import (
    PADDLE_SUBSCRIPTION_GRACE_DAYS,
    Subscription,
    User,
    UserAuditLog,
)
from app.user_audit_log_utils import UserAuditLogAction

# the shortest plan is monthly, so a subscription cannot have lapsed before
# that plus the grace period. Using the shortest period keeps the detector
# conservative: it under-reports rather than crying wolf on yearly plans.
DEFAULT_WINDOW_DAYS = 31 + PADDLE_SUBSCRIPTION_GRACE_DAYS

# audit log entries written by the Paddle callback
_STARTS_SUBSCRIPTION = (
    UserAuditLogAction.Upgrade.value,
    UserAuditLogAction.SubscriptionExtended.value,
)
_PADDLE_ACTIONS = _STARTS_SUBSCRIPTION + (
    UserAuditLogAction.SubscriptionCancelled.value,
)


class Stats:
    def __init__(self):
        self.users_checked = 0
        self.suspicious = 0
        self.errors = 0

    def print(self):
        print("---")
        print(f"users with a Paddle extension : {self.users_checked}")
        print(f"suspicious extensions found   : {self.suspicious}")
        print(f"errors                        : {self.errors}")
        print("---")


def users_with_extension() -> List[int]:
    """ids of the users who got a Paddle subscription extension at some point"""
    rows = (
        Session.query(UserAuditLog.user_id)
        .filter(
            UserAuditLog.action == UserAuditLogAction.SubscriptionExtended.value,
        )
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def paddle_audit_log(user_id: int) -> List[UserAuditLog]:
    return (
        Session.query(UserAuditLog)
        .filter(
            UserAuditLog.user_id == user_id,
            UserAuditLog.action.in_(_PADDLE_ACTIONS),
        )
        .order_by(UserAuditLog.created_at)
        .all()
    )


def suspicious_extensions(
    entries: List[UserAuditLog], window_days: int, ignore_window: bool
) -> List[UserAuditLog]:
    """
    Extensions that a legitimate re-subscription cannot explain: no cancellation
    since the subscription period started and, unless ignore_window is set, too
    early for that period to have lapsed on its own.
    """
    found = []
    # the entry that started the subscription period the extension lands in
    period_start: Optional[UserAuditLog] = None
    cancelled_since = False

    for entry in entries:
        if entry.action == UserAuditLogAction.SubscriptionCancelled.value:
            # a cancellation lets the user legitimately subscribe again
            cancelled_since = True
            continue

        if entry.action == UserAuditLogAction.SubscriptionExtended.value:
            within_window = (
                period_start is not None
                and (entry.created_at - period_start.created_at).days <= window_days
            )
            if not cancelled_since and (ignore_window or within_window):
                found.append(entry)

        # both Upgrade and SubscriptionExtended start a new paid period
        period_start = entry
        cancelled_since = False

    return found


def paddle_payer_email(subscription_id: str) -> str:
    """the email Paddle has for a subscription, to compare with the account"""
    try:
        r = requests.post(
            "https://vendors.paddle.com/api/2.0/subscription/users",
            data={
                "vendor_id": PADDLE_VENDOR_ID,
                "vendor_auth_code": PADDLE_AUTH_CODE,
                "subscription_id": subscription_id,
            },
            timeout=30,
        )
        res = r.json()
    except (requests.RequestException, ValueError) as e:
        return f"<paddle call failed: {e}>"

    if not res.get("success"):
        return f"<paddle error: {res.get('error')}>"

    response = res.get("response") or []
    if not response:
        return "<unknown to paddle>"

    return response[0].get("user_email") or "<no email>"


def describe(user: User, entry: UserAuditLog, with_paddle: bool) -> str:
    sub: Optional[Subscription] = Subscription.get_by(user_id=user.id)
    current = (
        f"subscription_id={sub.subscription_id} plan={sub.plan_name()} "
        f"next_bill_date={sub.next_bill_date} cancelled={sub.cancelled}"
        if sub
        else "no subscription row anymore"
    )

    payer = ""
    if with_paddle and sub:
        payer = f" | paddle payer={paddle_payer_email(sub.subscription_id)}"

    return (
        f"user id={user.id} ({user.email}) got an unexplained Paddle extension "
        f"at {entry.created_at} | current: {current}{payer}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check_paddle_passthrough_abuse",
        description=(
            "Find Paddle subscription extensions that a legitimate "
            "re-subscription cannot explain, ie the fingerprint of a "
            "subscription taken over through the checkout passthrough"
        ),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=(
            "how long after the start of a subscription period an extension is "
            "considered impossible without a cancellation "
            f"(default {DEFAULT_WINDOW_DAYS}, ie the shortest plan plus its grace "
            "period). Raise it to 379 to cover yearly plans, at the cost of "
            "false positives on users who simply let their plan lapse"
        ),
    )
    parser.add_argument(
        "--all-extensions",
        action="store_true",
        help=(
            "report every extension with no cancellation before it, ignoring the "
            "window. Catches takeovers of lapsed-looking subscriptions but needs "
            "manual triage"
        ),
    )
    parser.add_argument(
        "--paddle",
        action="store_true",
        help=(
            "ask the Paddle API which email paid for the subscription each "
            "reported user now holds. A mismatch with the account email is a "
            "strong hint, but not proof: people do pay with another address"
        ),
    )
    args = parser.parse_args()

    if args.paddle and not PADDLE_AUTH_CODE:
        print("PADDLE_AUTH_CODE is not set, cannot query the Paddle API")
        return 2

    if args.all_extensions:
        print("mode: every extension with no preceding cancellation")
    else:
        print(
            f"mode: extensions landing within {args.window_days} days of the start "
            "of a subscription period, with no cancellation before them"
        )

    stats = Stats()
    for user_id in users_with_extension():
        stats.users_checked += 1

        user: Optional[User] = User.get(user_id)
        if not user:
            # account deleted since, nothing left to look at
            continue

        try:
            entries = suspicious_extensions(
                paddle_audit_log(user_id),
                args.window_days,
                ignore_window=args.all_extensions,
            )
        except Exception as e:
            stats.errors += 1
            print(f"ERROR checking user {user_id}: {e}")
            continue

        for entry in entries:
            stats.suspicious += 1
            print(f"SUSPICIOUS: {describe(user, entry, args.paddle)}")

    stats.print()

    if stats.suspicious:
        print(
            "each hit means the subscription row of that user was rewritten by a "
            "checkout they could not have started themselves. Compare the payer "
            "in the Paddle dashboard with the account before acting, then move "
            "the subscription back by hand."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
