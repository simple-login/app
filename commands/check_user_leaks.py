import csv
import sys

from dataclasses import dataclass
from typing import List, Optional

from app.models import User
from app.utils import sanitize_email, canonicalize_email


@dataclass
class UserCheckResult:
    has_leak: bool
    user: Optional[User]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def check_user(row: List[str]) -> UserCheckResult:
    email = row[1]
    password = row[2]

    email = sanitize_email(email)
    canonical_email = canonicalize_email(email)
    user = User.get_by(email=email) or User.get_by(email=canonical_email)

    if not user:
        return UserCheckResult(has_leak=False, user=None)

    password_leaked = user.check_password(password)
    return UserCheckResult(has_leak=password_leaked, user=user)


def main(leaks_file: str):
    exists_count = 0
    not_exists_count = 0
    password_leaked_count = 0

    def print_report():
        eprint(f"Exists: {exists_count}")
        eprint(f"Not exists: {not_exists_count}")
        eprint(f"Passwords leaked: {password_leaked_count}")

    with open(leaks_file, "r") as f:
        reader = csv.reader(f, delimiter=",", quotechar='"')
        i = 0
        for row in reader:
            i += 1
            if i % 100 == 0:
                print_report()
            result = check_user(row)
            if result.user is not None:
                user: User = result.user
                exists_count += 1
                if result.has_leak:
                    password_leaked_count += 1
                    active = user.is_active()
                    eprint(
                        f"- [{i}] User {user} (active={active}) had their password leaked"
                    )
                    if active:
                        print(user.id)
            else:
                not_exists_count += 1

    print_report()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        eprint("Usage: python check_user_leaks.py <file.csv>")
        sys.exit(1)

    main(sys.argv[1])
