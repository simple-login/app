#!/usr/bin/env python3
import argparse
import time

from sqlalchemy import func
from app.models import Alias
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Backfill alias", description="Update alias notes and backfill flag"
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
step = 10000
noteSql = "(note = 'Created through Proton' or note = 'Created through partner Proton')"
alias_query = f"UPDATE alias set note = NULL, flags = flags | :flag where id>=:start AND id<:end and {noteSql}"
updated = 0
start_time = time.time()
for batch_start in range(alias_id_start, max_alias_id, step):
    rows_done = Session.execute(
        alias_query,
        {
            "start": batch_start,
            "end": batch_start + step,
            "flag": Alias.FLAG_PARTNER_CREATED,
        },
    )
    updated += rows_done.rowcount
    Session.commit()
    elapsed = time.time() - start_time
    last_batch_id = batch_start + step
    time_per_alias = elapsed / (last_batch_id)
    remaining = max_alias_id - last_batch_id
    time_remaining = remaining / time_per_alias
    hours_remaining = time_remaining / 60.0
    print(
        f"\rAlias {batch_start}/{max_alias_id} {updated} {hours_remaining:.2f} mins remaining"
    )
print("")
