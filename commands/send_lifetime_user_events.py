#!/usr/bin/env python3
import argparse
import sys
import time

from sqlalchemy import func

from app.db import Session
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import UserPlanChanged, EventContent
from app.models import PartnerUser, User

parser = argparse.ArgumentParser(
    prog="Backfill alias", description="Send lifetime users to proton"
)
parser.add_argument(
    "-s", "--start_pu_id", default=0, type=int, help="Initial partner_user_id"
)
parser.add_argument(
    "-e", "--end_pu_id", default=0, type=int, help="Last partner_user_id"
)
parser.add_argument("-t", "--step", default=10000, type=int, help="Step to use")
parser.add_argument("-u", "--user", default="", type=str, help="User to sync")
parser.add_argument(
    "-l", "--lifetime", action="store_true", help="Only sync lifetime users"
)

args = parser.parse_args()
pu_id_start = args.start_pu_id
max_pu_id = args.end_pu_id
user_id = args.user
only_lifetime = args.lifetime
step = args.step

if max_pu_id == 0:
    max_pu_id = Session.query(func.max(PartnerUser.id)).scalar()

if user_id:
    try:
        user_id = int(user_id)
    except ValueError:
        user = User.get_by(email=user_id)
        if not user:
            print(f"User {user_id} not found")
            sys.exit(1)
        print(f"Limiting to user {user_id}")
        user_id = user.id
        # So we only have one loop
        step = max_pu_id

print(f"Checking partner user {pu_id_start} to {max_pu_id}")
done = 0
start_time = time.time()
with_lifetime = 0
with_plan = 0
with_free = 0
for batch_start in range(pu_id_start, max_pu_id, step):
    query = Session.query(User).join(PartnerUser, PartnerUser.user_id == User.id)
    if user_id:
        query = query.filter(User.id == user_id)
    else:
        query = query.filter(
            PartnerUser.id >= batch_start, PartnerUser.id < batch_start + step
        )
    if only_lifetime:
        query = query.filter(
            User.lifetime == True,  # noqa :E712
        )
    users = query.all()
    for user in users:
        # Just in case the == True cond is wonky
        if user.lifetime:
            event = UserPlanChanged(lifetime=True)
            with_lifetime += 1
        else:
            plan_end = user.get_active_subscription_end(
                include_partner_subscription=False
            )
            if plan_end:
                event = UserPlanChanged(plan_end_time=plan_end.timestamp)
                with_plan += 1
            else:
                event = UserPlanChanged()
                with_free += 1
        EventDispatcher.send_event(user, EventContent(user_plan_change=event))
        Session.flush()
    Session.commit()
    elapsed = time.time() - start_time
    last_batch_id = batch_start + step
    time_per_alias = elapsed / (last_batch_id)
    remaining = max_pu_id - last_batch_id
    time_remaining = remaining / time_per_alias
    hours_remaining = time_remaining / 60.0
    print(
        f"artnerUser {batch_start}/{max_pu_id} lifetime {with_lifetime} paid {with_plan} free {with_free} {hours_remaining:.2f} mins remaining"
    )
print(f"Sent lifetime {with_lifetime} paid {with_plan} free {with_free}")
