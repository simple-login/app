#!/usr/bin/env python3
import argparse
import random
import time

from sqlalchemy import func

from app import config
from app.models import Alias, Contact
from app.db import Session

parser = argparse.ArgumentParser(
    prog=f"Replace {config.NOREPLY}",
    description=f"Replace {config.NOREPLY} from contacts reply email",
)
args = parser.parse_args()

max_alias_id: int = Session.query(func.max(Alias.id)).scalar()

start = time.time()
tests = 1000
for i in range(tests):
    alias = (
        Alias.filter(Alias.id > int(random.random() * max_alias_id))
        .order_by(Alias.id.asc())
        .limit(1)
        .first()
    )
    contact = Contact.filter_by(alias_id=alias.id).order_by(Contact.id.asc()).first()
    mailboxes = alias.mailboxes
    user = alias.user
    if i % 10:
        print("{i} -> {alias.id}")

end = time.time()
time_taken = end - start
print(f"Took {time_taken} -> {time_taken / tests} per test")
