from __future__ import annotations

from cachetools import TTLCache, cached

from app.db import Session
from app.log import LOG
from app.models import GlobalSenderBlacklist
from app.regex_utils import regex_search


# Cache enabled patterns briefly to avoid a DB query per inbound email.
# Admin changes should take effect quickly but don't need to be instant.
@cached(cache=TTLCache(maxsize=1, ttl=30))
def _get_enabled_patterns() -> list[str]:
    return [
        r.pattern
        for r in Session.query(GlobalSenderBlacklist)
        .filter(GlobalSenderBlacklist.enabled.is_(True))
        .order_by(GlobalSenderBlacklist.id.asc())
        .all()
    ]


def is_sender_globally_blocked(*candidates: str) -> bool:
    """Return True if any candidate sender string matches the global blacklist.

    Typical candidates:
      - SMTP envelope MAIL FROM
      - parsed header From address
    """

    patterns = _get_enabled_patterns()
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
                LOG.exception(
                    "Global sender blacklist regex failed: pattern=%s candidate=%s",
                    pattern,
                    candidate,
                )

    return False
