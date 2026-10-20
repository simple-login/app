#!/usr/bin/env python3
"""Count how many paid users were created thanks to a referral.

Input is either:
  --referral-id   the Referral.id
  --user-id       the id of the user who owns the referral(s)

A user is considered "created thanks to the referral" when their
User.referral_id points to the referral. A user is "paid" when
lifetime_or_active_subscription() returns True.
"""
import argparse
import sys

from app.models import Referral, User

parser = argparse.ArgumentParser(
    prog="count_paid_users_from_referral",
    description="Count paid users created thanks to a referral",
)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("-r", "--referral-id", type=int, help="Referral id")
group.add_argument(
    "-u", "--user-id", type=int, help="Id of the user that owns the referral(s)"
)
args = parser.parse_args()

if args.referral_id is not None:
    referrals = [Referral.get(args.referral_id)]
    if referrals[0] is None:
        print(f"Referral {args.referral_id} not found")
        sys.exit(1)
else:
    referrals = Referral.filter_by(user_id=args.user_id).all()
    if not referrals:
        print(f"No referral owned by user {args.user_id}")
        sys.exit(1)

referral_ids = [r.id for r in referrals]
print(f"Found {len(referral_ids)} referral(s): {referral_ids}")

# Fetch all users created thanks to the referral(s)
users = User.filter(User.referral_id.in_(referral_ids)).all()
print(f"Number of users created thanks to the referral(s): {len(users)}")

nb_paid = 0
for user in users:
    if user.lifetime_or_active_subscription():
        nb_paid += 1

print(f"Number of paid users: {nb_paid}")
