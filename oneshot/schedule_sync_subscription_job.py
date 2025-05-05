#!/usr/bin/env python3

import argparse
import sys
import time
from typing import Optional

from sqlalchemy import func

from app.db import Session
from app.jobs.sync_subscription_job import SyncSubscriptionJob
from app.models import PartnerUser, User, JobPriority


def process(start_pu_id: int, end_pu_id: int, step: int, only_lifetime: bool):
    print(
        f"Checking partner user {start_pu_id} to {end_pu_id} (step={step}) (only_lifetime={only_lifetime})"
    )
    start_time = time.time()
    processed = 0
    for batch_start in range(start_pu_id, end_pu_id, step):
        batch_end = min(batch_start + step, end_pu_id)
        query = (
            Session.query(User)
            .join(PartnerUser, PartnerUser.user_id == User.id)
            .filter(PartnerUser.id >= batch_start, PartnerUser.id < batch_end)
        )
        if only_lifetime:
            query = query.filter(
                User.lifetime == True,  # noqa :E712
            )
        users = query.all()
        for user in users:
            job = SyncSubscriptionJob(user)
            job.store_job_in_db(priority=JobPriority.Low, run_at=None, commit=False)
            processed += 1
        Session.commit()
        elapsed = time.time() - start_time
        if processed == 0:
            time_per_user = elapsed
        else:
            time_per_user = elapsed / processed

        remaining = end_pu_id - batch_end
        if remaining == 0:
            mins_remaining = 0
        else:
            mins_remaining = (time_per_user * remaining) / 60
        print(
            f"PartnerUser {batch_start}/{end_pu_id} | processed = {processed} | {mins_remaining:.2f} mins remaining"
        )


def main():
    parser = argparse.ArgumentParser(
        prog="Schedule Sync User Jobs",
        description="Create jobs to sync user subscriptions",
    )
    parser.add_argument(
        "-s", "--start_pu_id", default=0, type=int, help="Initial partner_user_id"
    )
    parser.add_argument(
        "-e", "--end_pu_id", default=0, type=int, help="Last partner_user_id"
    )
    parser.add_argument("-t", "--step", default=100, type=int, help="Step to use")
    parser.add_argument("-u", "--user", default="", type=str, help="User to sync")
    parser.add_argument(
        "-l", "--lifetime", action="store_true", help="Only sync lifetime users"
    )

    args = parser.parse_args()
    start_pu_id = args.start_pu_id
    end_pu_id = args.end_pu_id
    user_id = args.user
    only_lifetime = args.lifetime
    step = args.step

    if start_pu_id <= 0:
        start_pu_id = Session.query(func.min(PartnerUser.id)).scalar()

    if not end_pu_id:
        end_pu_id = Session.query(func.max(PartnerUser.id)).scalar()

    if user_id:
        try:
            user_id = int(user_id)
        except ValueError:
            user = User.get_by(email=user_id)
            if not user:
                print(f"User {user_id} not found")
                sys.exit(1)
            user_id = user.id
        print(f"Limiting to user {user_id}")
        partner_user: Optional[PartnerUser] = PartnerUser.get_by(user_id=user_id)
        if not partner_user:
            print(f"Could not find PartnerUser for user_id={user_id}")
            sys.exit(1)

        # So we only have one loop
        step = 1
        start_pu_id = partner_user.id
        end_pu_id = partner_user.id + 1  # Necessary to at least have 1 result

    process(
        start_pu_id=start_pu_id,
        end_pu_id=end_pu_id,
        step=step,
        only_lifetime=only_lifetime,
    )


if __name__ == "__main__":
    main()
