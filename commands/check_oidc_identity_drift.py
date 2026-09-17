#!/usr/bin/env python3
"""
Check (and optionally repair) "Sign in with SimpleLogin" identities that do not
belong to the owner of the alias they are linked to.

Usage
-----
    # report only (default, read-only)
    python -m commands.check_oidc_identity_drift

    # additionally revoke the affected identities and their grants
    python -m commands.check_oidc_identity_drift --fix
"""
import argparse
import sys
from typing import List, Optional

from sqlalchemy import func

from app.alias_utils import revoke_client_user
from app.db import Session
from app.models import Alias, Client, ClientUser, User

# how many client_user ids to look at per query
BATCH_SIZE = 1000


class Stats:
    def __init__(self):
        self.found = 0
        self.revoked = 0
        self.errors = 0

    def print(self):
        print("---")
        print(f"inconsistent identities found   : {self.found}")
        print(f"inconsistent identities revoked : {self.revoked}")
        print(f"errors                          : {self.errors}")
        print("---")


def drifted_client_users(batch_start: int, batch_end: int) -> List[ClientUser]:
    """
    ClientUser rows, ie OIDC subjects, linked to an alias owned by somebody
    else: the subject they produce is served to a user who never consented to
    it.
    """
    return (
        Session.query(ClientUser)
        .join(Alias, Alias.id == ClientUser.alias_id)
        .filter(ClientUser.user_id != Alias.user_id)
        .filter(ClientUser.id >= batch_start, ClientUser.id <= batch_end)
        .all()
    )


def describe(client_user: ClientUser) -> str:
    alias: Optional[Alias] = client_user.alias
    alias_owner: Optional[User] = alias.user if alias else None
    previous_owner: Optional[User] = (
        User.get(alias.original_owner_id) if alias and alias.original_owner_id else None
    )
    client: Optional[Client] = client_user.client

    transferred = (
        f", transferred from user {previous_owner.id}" if previous_owner else ""
    )
    return (
        f"client_user id={client_user.id} (OIDC sub={client_user.id}) "
        f"is assigned to user {client_user.user_id} but its alias "
        f"{alias.email if alias else client_user.alias_id} is owned by "
        f"user {alias_owner.id if alias_owner else '?'}{transferred} "
        f"| client={client.name if client else client_user.client_id}"
        f" ({client.oauth_client_id if client else '?'})"
        f" | created_at={client_user.created_at}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check_oidc_identity_drift",
        description=(
            "Find client_user rows, ie OpenID Connect subjects, linked to an alias "
            "owned by another user, usually the leftover of an alias transfer "
            "performed before the issue was fixed"
        ),
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="revoke the affected identities and their grants instead of only reporting them",
    )
    args = parser.parse_args()

    stats = Stats()
    max_id = Session.query(func.max(ClientUser.id)).scalar()
    if not max_id:
        print("no client_user row found")
        return 0

    print(
        f"checking client_user ids up to {max_id}, looking for identities linked "
        f"to an alias owned by another user"
    )
    if args.fix:
        print("mode: FIX, the inconsistent identities will be revoked")
    else:
        print("mode: CHECK ONLY, nothing is changed (use --fix to revoke)")

    for batch_start in range(1, max_id + 1, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE - 1, max_id)
        for client_user in drifted_client_users(batch_start, batch_end):
            stats.found += 1
            print(f"INCONSISTENT: {describe(client_user)}")

            if not args.fix:
                continue

            try:
                # only that identity goes away, the alias itself is untouched
                revoke_client_user(client_user)
                Session.commit()
                stats.revoked += 1
                print(f"REVOKED: client_user {client_user.id}")
            except Exception as e:
                Session.rollback()
                stats.errors += 1
                print(f"ERROR revoking client_user {client_user.id}: {e}")

    stats.print()

    if stats.found and not args.fix:
        print(
            "run again with --fix to revoke those identities. The affected users "
            "will have to authorize the involved apps again, with a new OIDC "
            "subject."
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
