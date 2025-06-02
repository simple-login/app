#!/usr/bin/env python3
import argparse
import time

from sqlalchemy import func

from app.models import Alias, SLDomain
from app.db import Session

parser = argparse.ArgumentParser(
    prog="Mark partner created aliases with the PARTNER_CREATED flag",
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

print(f"Updating aliases from {alias_id_start} to {max_alias_id}")

domains = SLDomain.filter(SLDomain.partner_id.isnot(None)).all()
cond = [f"email like '%{domain.domain}'" for domain in domains]
sql_or_cond = " OR ".join(cond)
sql = f"UPDATE alias set flags = (flags | :flag) WHERE id >= :start and id<:end and flags & :flag = 0 and ({sql_or_cond})"
print(sql)

step = 1000
updated = 0
start_time = time.time()
for batch_start in range(alias_id_start, max_alias_id, step):
    updated += Session.execute(
        sql,
        {
            "start": batch_start,
            "end": batch_start + step,
            "flag": Alias.FLAG_PARTNER_CREATED,
        },
    ).rowcount
    elapsed = time.time() - start_time
    time_per_alias = elapsed / (batch_start - alias_id_start + step)
    last_batch_id = batch_start + step
    remaining = max_alias_id - last_batch_id
    time_remaining = (max_alias_id - last_batch_id) * time_per_alias
    hours_remaining = time_remaining / 3600.0
    percent = int(
        ((batch_start - alias_id_start) * 100) / (max_alias_id - alias_id_start)
    )
    print(
        f"\rAlias {batch_start}/{max_alias_id} {percent}% {updated} updated {hours_remaining:.2f}hrs remaining"
    )
print(f"Updated aliases up to {max_alias_id}")
