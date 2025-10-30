from typing import Optional

import sys
import time

from app.config import URL
from app.db import Session
from app.email_utils import render, send_email
from app.models import User
from app.utils import random_string

_SUFFIX = ":invalid"
PASSWORD_RESET_LINK = f"{URL}/auth/forgot_password"
ACCOUNT_SETTINGS_LINK = f"{URL}/dashboard/account_setting"


def reset_user_password(user: User):
    random_password = random_string(length=20, include_digits=True)
    user.set_password(random_password)
    user.password = f"{user.password}{_SUFFIX}"
    Session.commit()


def send_user_email(user: User):
    send_email(
        to_email=user.email,
        subject="Your SimpleLogin password has been reset",
        plaintext=render(
            template_name="/transactional/reset_password_leak.txt",
            user=user,
            password_reset_link=PASSWORD_RESET_LINK,
            account_link=ACCOUNT_SETTINGS_LINK,
        ),
        html=render(
            template_name="transactional/reset_password_leak.html",
            user=user,
            password_reset_link=PASSWORD_RESET_LINK,
            account_link=ACCOUNT_SETTINGS_LINK,
        ),
        retries=3,
    )


def handle_user(user_id: str):
    user_id = int(user_id)
    user: Optional[User] = User.get(user_id)
    if user is None:
        raise Exception(f"User {user_id} not found")
    if not user.is_active():
        print(f"User {user_id} is not active")
        return

    if user.password.endswith(_SUFFIX):
        print(f"User {user_id} has already been reset")
        return

    reset_user_password(user)
    send_user_email(user)


def main(user_ids_file: str):
    processed = 0
    success = 0
    errors = 0
    start_time = time.time()

    with open(user_ids_file, "r") as f:
        lines = f.readlines()
        total_lines = len(lines)
        for line in lines:
            user_id = line.strip()
            if not user_id:
                continue
            processed += 1
            if processed % 100 == 0 and total_lines > processed > 0:
                elapsed = time.time() - start_time
                remaining_lines = total_lines - processed
                time_per_user = elapsed / processed
                remaining_time_seconds = remaining_lines * time_per_user
                remaining_time_minutes = remaining_time_seconds / 60
                print("---")
                print(f"Processed {processed}/{total_lines} lines in {elapsed} seconds")
                print(f"Remaining time {remaining_time_minutes} minutes.")
                print(f"Report: success={success} | errors={errors}")
                print("---")

            try:
                handle_user(user_id)
                success += 1
            except Exception as e:
                print(f"Error processing line {line}: {e}")
                errors += 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python handle_leaks.py <user_id_list>")
        sys.exit(1)

    main(sys.argv[1])
