"""SMTP-level health and readiness probes for the email handler.

The email handler is a single-threaded aiosmtpd server, so it cannot serve an
HTTP endpoint. Orchestrators instead issue ``RCPT TO:<health@probe.invalid>``
or ``RCPT TO:<ready@probe.invalid>``; the reply carries a marker that a plain
SMTP server would never produce (see ``scripts/smtp_probe.py``).
"""

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Optional

from sqlalchemy import create_engine, text

from app import config
from app.log import LOG

HEALTH_ADDRESS = "health@probe.invalid"
READY_ADDRESS = "ready@probe.invalid"

HEALTH_OK = "250 2.0.0 SL-PROBE HEALTH OK"
READY_OK = "250 2.0.0 SL-PROBE READY OK"
READY_FAIL = "451 4.3.0 SL-PROBE READY FAIL"

DEFAULT_READINESS_TIMEOUT = 2.0


def database_check(timeout: float = DEFAULT_READINESS_TIMEOUT) -> Callable[[], None]:
    """Return a callable running ``SELECT 1`` on its own DB connection.

    The global ``app.db.Session`` is deliberately not used: readiness must not
    share (or wait for) a connection with mail processing. Connect and query
    timeouts keep a stalled DB from pinning the worker thread forever.
    """
    engine = create_engine(
        config.DB_URI,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={
            "application_name": f"{config.DB_CONN_NAME}-readiness",
            "connect_timeout": max(1, int(timeout)),
            "options": f"-c statement_timeout={int(timeout * 1000)}",
        },
    )

    def check() -> None:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    return check


class ReadinessChecker:
    """Run a blocking check off the event loop, bounded in time and concurrency.

    At most one check is outstanding: while a stalled one is still running, new
    requests fail immediately instead of piling up threads.
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
