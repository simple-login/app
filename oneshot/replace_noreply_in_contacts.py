#!/usr/bin/env python3
import argparse
import time


from app import config
from app.email_utils import generate_reply_email
from app.email_validation import is_valid_email
from app.models import Alias
from app.db import Session

parser = argparse.ArgumentParser(
    prog=f"Replace {config.NOREPLY}",
    description=f"Replace {config.NOREPLY} from contacts reply email",
)
args = parser.parse_args()

el_query = "SELECT id, alias_id, website_email from contact where id>=:last_id AND reply_email=:reply_email ORDER BY id ASC LIMIT :step"
update_query = "UPDATE contact SET reply_email=:reply_email WHERE id=:contact_id "
updated = 0
start_time = time.time()
step = 100
last_id = 0
print(f"Replacing contacts with reply_email={config.NOREPLY}")
while True:
    rows = Session.execute(
        el_query, {"last_id": last_id, "reply_email": config.NOREPLY, "step": step}
    )
    loop_updated = 0
    for row in rows:
        contact_id = row[0]
        alias_id = row[1]
        last_id = contact_id
        website_email = row[2]
        contact_email_for_reply = website_email if is_valid_email(website_email) else ""
        alias = Alias.get(alias_id)
        if alias is None:
            print(f"CANNOT find alias {alias_id} in database for contact {contact_id}")
        reply_email = generate_reply_email(contact_email_for_reply, alias)
        print(
            f"Replacing contact {contact_id} with {website_email} reply_email for {reply_email}"
        )
        Session.execute(
            update_query, {"contact_id": row[0], "reply_email": reply_email}
        )
        Session.commit()
        updated += 1
        loop_updated += 1
    elapsed = time.time() - start_time
    print(f"\rContact {last_id} done")
    if loop_updated == 0:
        break
print("")
