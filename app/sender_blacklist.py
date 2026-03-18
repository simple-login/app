from __future__ import annotations

from cachetools import TTLCache, cached

from app.db import Session
from app.log import LOG
from app.models import GlobalSenderBlacklist
from app.regex_utils import regex_search


# Cache enabled patterns briefly to avoid a DB query per inbound email.
# Admin changes should take effect quickly but don't need to be instant.
@cached(cache=TTLCache(maxsize=128, ttl=30))
def _get_enabled_global_patterns() -> list[str]:
    return [
        r.pattern
        for r in Session.query(GlobalSenderBlacklist)
        .filter(
            GlobalSenderBlacklist.enabled.is_(True),
            GlobalSenderBlacklist.user_id.is_(None),
        )
        .order_by(GlobalSenderBlacklist.id.asc())
        .all()
    ]


# Per-user cache: keep it small-ish but avoid a DB query per email per user.
@cached(cache=TTLCache(maxsize=128, ttl=30))
def _get_enabled_user_patterns(user_id: int) -> list[str]:
    return [
        r.pattern
        for r in Session.query(GlobalSenderBlacklist)
        .filter(
            GlobalSenderBlacklist.enabled.is_(True),
            GlobalSenderBlacklist.user_id == user_id,
        )
        .order_by(GlobalSenderBlacklist.id.asc())
        .all()
    ]


def is_sender_blocked_for_user(user_id: int | None, *candidates: str) -> bool:
    """Return True if any candidate sender string matches:

    - the global sender blacklist (user_id is NULL), OR
    - the given user's sender blacklist (user_id matches)

    Typical candidates:
      - SMTP envelope MAIL FROM
      - parsed header From address
    """

    patterns: list[str] = []
    patterns.extend(_get_enabled_global_patterns())
    if user_id is not None:
        patterns.extend(_get_enabled_user_patterns(int(user_id)))

    if not patterns:
        return False

    for candidate in candidates:
        if not candidate:
            continue
        # Ignore bounce/null reverse-path
        if candidate == "<>":
            continue

        for pattern in patterns:
            try:
                if regex_search(pattern, candidate):
                    return True
            except Exception:
                # Never crash the SMTP handler because of a bad regex.
                # (Global or user entry — both are user-provided.)
                LOG.exception(
                    "Sender blacklist regex failed: user_id=%s pattern=%s candidate=%s",
                    user_id,
                    pattern,
                    candidate,
                )

    return False
