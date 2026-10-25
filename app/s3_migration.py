"""Copy the objects the DB references from the old storage to the new S3 bucket.

Keys stay identical, so no DB row is modified and old objects are never
deleted. The app must already be configured for the new bucket when this
runs; the old storage is read over its public root URL.
"""

import enum
from io import BytesIO
from typing import Iterator, Optional, Tuple

import arrow
import botocore.exceptions
import requests
from urllib.parse import quote

from sqlalchemy import func

from app import s3
from app.db import Session
from app.log import LOG
from app.models import File, RefusedEmail

MODEL_FILE = "file"
MODEL_REFUSED_EMAIL = "refused_email"


class Outcome(enum.Enum):
    EXISTS = "exists"
    COPIED = "copied"
    MISSING = "missing"
    FAILED = "failed"
    WOULD_COPY = "would_copy"


def iter_keys(
    batch_size: int, only: Optional[str] = None, start_id: int = 0
) -> Iterator[Tuple[str, int, str]]:
    """Yield (model_name, id, key) for every S3 key the DB still references.

    Walks fixed id windows, like scripts/sanitize_contact_names.py does: the
    windows bound the work per query no matter how far apart the rows are.
    Refused emails whose objects the cleanup cron is about to delete (already
    deleted, or expiring within a day) are skipped.
    """
    if only is not None and only not in (MODEL_FILE, MODEL_REFUSED_EMAIL):
        raise ValueError(f"unknown model {only}")

    if only is None or only == MODEL_FILE:
        max_id = Session.query(func.max(File.id)).scalar() or 0
        last_batch_id = start_id
        while last_batch_id < max_id:
            # read the keys as plain tuples: the rows leave the session at the
            # end of every batch, and only these survive the walk
            rows = (
                Session.query(File.id, File.path)
                .filter(
                    File.id > last_batch_id,
                    File.id <= last_batch_id + batch_size,
                )
                .order_by(File.id)
                .all()
            )
            for row_id, path in rows:
                yield MODEL_FILE, row_id, path
            # do not keep every row we looked at in the identity map
            Session.expunge_all()
            last_batch_id += batch_size

    if only is None or only == MODEL_REFUSED_EMAIL:
        # rows expiring within a day are left to the delete_refused_emails cron
        min_delete_at = arrow.now().shift(days=1)
        max_id = Session.query(func.max(RefusedEmail.id)).scalar() or 0
        last_batch_id = start_id
        while last_batch_id < max_id:
            rows = (
                Session.query(
                    RefusedEmail.id,
                    RefusedEmail.full_report_path,
                    RefusedEmail.path,
                )
                .filter(
                    RefusedEmail.id > last_batch_id,
                    RefusedEmail.id <= last_batch_id + batch_size,
                    RefusedEmail.deleted.is_(False),
                    RefusedEmail.delete_at > min_delete_at,
                )
                .order_by(RefusedEmail.id)
                .all()
            )
            for row_id, full_report_path, path in rows:
                yield MODEL_REFUSED_EMAIL, row_id, full_report_path
                if path:
                    yield MODEL_REFUSED_EMAIL, row_id, path
            Session.expunge_all()
            last_batch_id += batch_size


def migrate_key(key: str, old_root: str, apply: bool, timeout: float) -> Outcome:
    """Copy one key from the old storage to the current bucket."""
    if s3.exists(key):
        return Outcome.EXISTS

    url = f"{old_root.rstrip('/')}/{quote(key)}"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        LOG.w("migrate_s3_objects: request failed for %s", key)
        return Outcome.FAILED

    if resp.status_code == 404:
        return Outcome.MISSING
    if not resp.ok:
        LOG.w(
            "migrate_s3_objects: GET %s returned %s",
            key,
            resp.status_code,
        )
        return Outcome.FAILED

    if not apply:
        return Outcome.WOULD_COPY

    content_type = resp.headers.get("Content-Type")
    content_disposition = resp.headers.get("Content-Disposition")
    if content_disposition is None and key.endswith(".eml"):
        basename = key.rsplit("/", 1)[-1]
        content_disposition = f'attachment; filename="{basename}"'

    try:
        s3.upload_raw(
            key,
            BytesIO(resp.content),
            content_type=content_type,
            content_disposition=content_disposition,
        )
    except botocore.exceptions.BotoCoreError:
        LOG.w("migrate_s3_objects: upload failed for %s", key)
        return Outcome.FAILED
    return Outcome.COPIED
