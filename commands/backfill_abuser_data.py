#!/usr/bin/env python3
import argparse
from typing import List

from sqlalchemy import func

from app.abuser import mark_user_as_abuser
from app.db import Session
from app.models import User, AbuserData

parser = argparse.ArgumentParser(
    prog="Backfill abuser data",
    description="Iterate over disabled users and generate abuser bundle",
)
args = parser.parse_args()

print("I'm going to generate abuser bundle for disabled users.")

user_id_start: int = 0
user_id_end: int = Session.query(func.max(User.id)).scalar()
step = 1000
total_disabled_users: int = 0
archived_users: int = 0

for batch_start in range(user_id_start, user_id_end + 1, step):
    users: List[User] = (
        Session.query(User)
        .filter(User.id >= batch_start, User.id < batch_start + step)
        .all()
    )

    for user in users:
        if not user.disabled:
            continue

        total_disabled_users += 1

        if not user.email:
            print(f"Disabled user {user.id} has no email address. Skipping...")
            continue

        abuser_bundles_count: int = (
            Session.query(AbuserData).filter(AbuserData.user_id == user.id).count()
        )

        if abuser_bundles_count:
            print(f"Disabled user {user.id} has already been archived. Skipping...")
            continue

        try:
            mark_user_as_abuser(
                user, "User was archived by 'backfill abuser data' one-shot job."
            )
            archived_users += 1
        except Exception:
            print(f"Failed to archive user {user.id}. Skipping...")

print(
    f"Finished generating abuser bundle for disabled users. Archived {archived_users} users out of {total_disabled_users} disabled users."
)
