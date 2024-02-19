#!/usr/bin/env python3
import argparse
import time

from sqlalchemy import func
from app.models import Alias
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Backfill alias", description="Backfill alias las use"
)
parser.add_argument(
    "-s", "--start_alias_id", default=0, type=int, help="Initial alias_id"
)
parser.add_argument("-e", "--end_alias_id", default=0, type=int, help="Last alias_id")

args = parser.parse_args()
alias_id_start = args.start_alias_id
max_alias_id = args.end_alias_id
if max_alias_id == 0:
    max_alias_id = Session.query(func.max(Alias.id)).scalar()

print(f"Checking alias {alias_id_start} to {max_alias_id}")
step = 1000
el_query = "SELECT alias_id, MAX(id) from email_log where alias_id>=:start AND alias_id < :end GROUP BY alias_id"
alias_query = "UPDATE alias set last_email_log_id = :el_id where id = :alias_id"
updated = 0
start_time = time.time()
for batch_start in range(alias_id_start, max_alias_id, step):
    rows = Session.execute(el_query, {"start": batch_start, "end": batch_start + step})
    for row in rows:
        Session.execute(alias_query, {"alias_id": row[0], "el_id": row[1]})
        Session.commit()
        updated += 1
    elapsed = time.time() - start_time
    time_per_alias = elapsed / (updated + 1)
    last_batch_id = batch_start + step
    remaining = max_alias_id - last_batch_id
    time_remaining = (max_alias_id - last_batch_id) * time_per_alias
    hours_remaining = time_remaining / 3600.0
    print(
        f"\rAlias {batch_start}/{max_alias_id} {updated} {hours_remaining:.2f}hrs remaining"
    )
print("")
