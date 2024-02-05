#!/usr/bin/env python3

from sqlalchemy import func

from app.models import Alias
from app.db import Session

max_alias_id = Session.query(func.max(Alias.id)).scalar()

step = 1000
el_query = "SELECT alias_id, MAX(id) from email_log where alias_id>=:start AND alias_id < :end GROUP BY alias_id"
alias_query = "UPDATE alias set last_email_log_id = :el_id where id = :alias_id"
updated = 0
for batch_start in range(0, max_alias_id, step):
    rows = Session.execute(el_query, {"start": batch_start, "end": batch_start + step})
    for row in rows:
        rows = Session.execute(alias_query, {"alias_id": row[0], "el_id": row[1]})
        updated += 1
    print(f"\rAlias {batch_start}/{max_alias_id} {updated}")
print("")
