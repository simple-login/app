"""SMTP-level health and readiness probes for the email handler.

The email handler is a single-threaded aiosmtpd server, so it cannot serve an
HTTP endpoint. Orchestrators instead issue ``RCPT TO:<health@probe.invalid>``
or ``RCPT TO:<ready@probe.invalid>``; the reply carries a marker that a plain
SMTP server would never produce (see ``scripts/smtp_probe.py``).
"""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from sqlalchemy import text

from app.db import Session
from app.log import LOG

HEALTH_ADDRESS = "health@probe.invalid"
READY_ADDRESS = "ready@probe.invalid"

HEALTH_OK = "250 2.0.0 SL-PROBE HEALTH OK"
READY_OK = "250 2.0.0 SL-PROBE READY OK"
READY_FAIL = "451 4.3.0 SL-PROBE READY FAIL"

DEFAULT_READINESS_TIMEOUT = 2.0


def database_check() -> None:
    """Run ``SELECT 1`` through the app's own ``Session`` and pooled engine.

    Going through the same path as mail processing makes readiness fail when
    that path is broken (pool exhausted, engine pointing at a dead backend,
    session in a failed transaction), not just when Postgres is unreachable.

    It runs on the ReadinessChecker's worker thread; that thread's session is
    removed afterwards so no pooled connection stays checked out.
    """
    try:
        Session.execute(text("SELECT 1"))
    finally:
        Session.remove()


class ReadinessChecker:
    """Run a blocking check off the event loop, bounded in time and concurrency.

    At most one check is outstanding: while a stalled one is still running, new
    requests fail immediately instead of piling up threads.

    The timeout bounds the *reply*, not the check. A query running through the
    pool cannot be interrupted, so a stalled query (or a pool checkout waiting
    on ``pool_timeout``) keeps its worker thread until the driver or pool gives
    up. Readiness reports not ready meanwhile and recovers once it returns.
    """

    def __init__(
        self, check: Callable[[], None], timeout: float = DEFAULT_READINESS_TIMEOUT
    ) -> None:
        self._check = check
        self._timeout = timeout
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ready")
        self._outstanding: Optional[Future] = None

    async def is_ready(self) -> bool:
        if self._outstanding is not None and not self._outstanding.done():
            LOG.w("readiness check still outstanding, reporting not ready")
            return False
        self._outstanding = self._executor.submit(self._check)
        try:
            await asyncio.wait_for(
                asyncio.wrap_future(self._outstanding), self._timeout
            )
        except asyncio.TimeoutError:
            LOG.w("readiness check timed out after %ss", self._timeout)
            return False
        except Exception as e:
            LOG.w("readiness check failed: %s", e)
            return False
        return True
