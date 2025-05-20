#!/usr/bin/env python3
import argparse
from typing import List

from app.abuser_utils import check_if_abuser_email, mark_user_as_abuser
from app.db import Session
from app.models import User

parser = argparse.ArgumentParser(
    prog="Backfill abuser data",
    description="Iterate over disabled users and generate abuser bundle",
)
args = parser.parse_args()

print("I'm going to generate abuser bundle for disabled users.")

disabled_users: List[User] = Session.query(User).filter(User.disabled == True).all()  # noqa: E712
archived_users: int = 0

for disabled_user in disabled_users:
    if not disabled_user.email:
        print(f"Disabled user {disabled_user.id} has no email address. Skipping...")
        continue

    if check_if_abuser_email(disabled_user.email):
        print(
            f"Disabled user {disabled_user.id} has already been archived. Skipping..."
        )
        continue

    try:
        mark_user_as_abuser(
            disabled_user, "User was archived by 'backfill abuser data' one-shot job."
        )
        archived_users += 1
    except Exception:
        print(f"Failed to archive user {disabled_user.id}. Skipping...")

print(
    f"Finished generating abuser bundle for disabled users. Archived {archived_users} users out of {len(disabled_users)} disabled users."
)
