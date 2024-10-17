#!/usr/bin/env python3
import argparse
import time

from sqlalchemy import func

from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import UserPlanChanged, EventContent
from app.models import PartnerUser
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Backfill alias", description="Update alias notes and backfill flag"
)
parser.add_argument(
    "-s", "--start_pu_id", default=0, type=int, help="Initial partner_user_id"
)
parser.add_argument(
    "-e", "--end_pu_id", default=0, type=int, help="Last partner_user_id"
)

args = parser.parse_args()
pu_id_start = args.start_pu_id
max_pu_id = args.end_pu_id
if max_pu_id == 0:
    max_pu_id = Session.query(func.max(PartnerUser.id)).scalar()

print(f"Checking partner user {pu_id_start} to {max_pu_id}")
step = 100
updated = 0
start_time = time.time()
with_premium = 0
for batch_start in range(pu_id_start, max_pu_id, step):
    partner_users = (
        Session.query(PartnerUser).filter(
            PartnerUser.id >= batch_start, PartnerUser.id < batch_start + step
        )
    ).all()
    for partner_user in partner_users:
        subscription_end = partner_user.user.get_active_subscription_end(
            include_partner_subscription=False
        )
        end_timestamp = None
        if subscription_end:
            with_premium += 1
            end_timestamp = subscription_end.timestamp
        event = UserPlanChanged(plan_end_time=end_timestamp)
        EventDispatcher.send_event(
            partner_user.user, EventContent(user_plan_change=event)
        )
        Session.flush()
        updated += 1
    Session.commit()
    elapsed = time.time() - start_time
    last_batch_id = batch_start + step
    time_per_alias = elapsed / (last_batch_id)
    remaining = max_pu_id - last_batch_id
    time_remaining = remaining / time_per_alias
    hours_remaining = time_remaining / 60.0
    print(
        f"\PartnerUser {batch_start}/{max_pu_id} {updated} {hours_remaining:.2f} mins remaining"
    )
print(f"With SL premium {with_premium}")
