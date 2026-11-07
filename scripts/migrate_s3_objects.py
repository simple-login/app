#!/usr/bin/env python3
"""Copy the stored objects (files, refused emails) to the new S3 bucket.

The app must already be configured for the new storage (config.BUCKET,
AWS_ENDPOINT_URL) before running this: the script reads the keys from the DB
and writes them to whatever bucket the config points at. The old storage is
the publicly readable one, given as --old-root. Keys are kept identical, so
no DB row is touched, and old objects are never deleted.

    # 1. switch the config to the new bucket and deploy
    # 2. dry run to see what would be copied
    python scripts/migrate_s3_objects.py --old-root https://old-static.example.com
    # 3. do it
    python scripts/migrate_s3_objects.py --old-root https://old-static.example.com --apply
    # 4. rerun the --apply pass later to pick up the rows created in between

To resume an interrupted run, pass the highest --start-id the log reached.
Use --only to handle one model at a time.
"""

import argparse
import sys
from collections import Counter

from app import config
from app.log import LOG
from app.s3_migration import iter_keys, migrate_key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--old-root",
        required=True,
        help="root URL of the old storage, must start with https://",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="upload the missing objects. Without it nothing is uploaded",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="how many ids to look at per query",
    )
    parser.add_argument(
        "--start-id",
        type=int,
        default=0,
        help="skip the rows with an id <= this, to resume an interrupted run",
    )
    parser.add_argument(
        "--only",
        choices=["file", "refused_email"],
        help="handle only this model",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="seconds to wait for the old storage per request",
    )
    args = parser.parse_args()

    if not args.old_root.startswith("https://"):
        LOG.e("--old-root must start with https://")
        return 1

    if config.LOCAL_FILE_UPLOAD:
        LOG.e(
            "LOCAL_FILE_UPLOAD is set: the config still points at the local "
            "disk. Configure the new S3 storage first"
        )
        return 1

    counts: Counter = Counter()
    for model_name, row_id, key in iter_keys(
        args.batch_size, only=args.only, start_id=args.start_id
    ):
        outcome = migrate_key(key, args.old_root, args.apply, args.timeout)
        counts[outcome] += 1
        LOG.i(f"{outcome.value}: {model_name} {row_id} {key}")

    mode = "applied" if args.apply else "dry run"
    LOG.i(f"Done ({mode}): " + ", ".join(f"{o.value}={c}" for o, c in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
