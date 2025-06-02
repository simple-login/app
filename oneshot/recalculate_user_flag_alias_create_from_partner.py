#!/usr/bin/env python3
import argparse
import time

from sqlalchemy import func
from app.models import Alias, User
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Backfill alias", description="Backfill user flags for partner alias created"
)
parser.add_argument(
    "-s", "--start_user_id", default=0, type=int, help="Initial user_id"
)
parser.add_argument("-e", "--end_user_id", default=0, type=int, help="Last user_id")

args = parser.parse_args()
user_id_start = args.start_user_id
max_user_id = args.end_user_id
if max_user_id == 0:
    max_user_id = Session.query(func.max(User.id)).scalar()

print(f"Checking user {user_id_start} to {max_user_id}")
step = 1000
el_query = "SELECT user_id, count(id) from alias where user_id>=:start AND user_id < :end AND flags & :alias_flag > 0 GROUP BY user_id"
user_update_query = "UPDATE users set flags = flags | :user_flag where id = :user_id"
updated = 0
start_time = time.time()
for batch_start in range(user_id_start, max_user_id, step):
    rows = Session.execute(
        el_query,
        {
            "start": batch_start,
            "end": batch_start + step,
            "alias_flag": Alias.FLAG_PARTNER_CREATED,
        },
    )
    for row in rows:
        if row[1] > 0:
            Session.execute(
                user_update_query,
                {"user_id": row[0], "user_flag": User.FLAG_CREATED_ALIAS_FROM_PARTNER},
            )
            Session.commit()
            updated += 1
    elapsed = time.time() - start_time
    time_per_alias = elapsed / (updated + 1)
    last_batch_id = batch_start + step
    remaining = max_user_id - last_batch_id
    time_remaining = (max_user_id - last_batch_id) * time_per_alias
    hours_remaining = time_remaining / 3600.0
    print(
        f"\rUser {batch_start}/{max_user_id} {updated} {hours_remaining:.2f}hrs remaining"
    )
print("")
