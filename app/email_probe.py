"""SMTP-level health and readiness probes for the email handler.

The email handler is a single-threaded aiosmtpd server, so it cannot serve an
HTTP endpoint. Orchestrators instead issue ``RCPT TO:<health@probe.invalid>``
or ``RCPT TO:<ready@probe.invalid>``; the reply carries a marker that a plain
SMTP server would never produce (see ``scripts/smtp_probe.py``).
"""

import asyncio
import select
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

import psycopg2
from psycopg2 import extensions

from app import config
from app.log import LOG

HEALTH_ADDRESS = "health@probe.invalid"
READY_ADDRESS = "ready@probe.invalid"

HEALTH_OK = "250 2.0.0 SL-PROBE HEALTH OK"
READY_OK = "250 2.0.0 SL-PROBE READY OK"
READY_FAIL = "451 4.3.0 SL-PROBE READY FAIL"

DEFAULT_READINESS_TIMEOUT = 2.0


def database_check(timeout: float = DEFAULT_READINESS_TIMEOUT) -> Callable[[], None]:
    """Return a callable running ``SELECT 1`` on a fresh DB connection.

    The global ``app.db`` engine/session is deliberately not used: readiness
    must not share (or wait for) a connection with mail processing.

    The connection is driven in psycopg2 async mode and polled with
    ``select()`` against one monotonic deadline covering connect and query.
    Server-side or TCP-level timeouts cannot do this: a peer that keeps
    acknowledging (e.g. pgbouncer in front of a stalled Postgres) never trips
    them, so the client has to enforce the wall-clock limit itself.

    Known caveat: libpq resolves the hostname synchronously inside
    ``connect``, so DNS is bounded only by the resolver's own timeout.
    """

    def wait(conn: Any, deadline: float) -> None:
        while True:
            state = conn.poll()
            if state == extensions.POLL_OK:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"readiness DB check exceeded {timeout}s")
            if state == extensions.POLL_READ:
                select.select([conn.fileno()], [], [], remaining)
            else:  # POLL_WRITE
                select.select([], [conn.fileno()], [], remaining)

    def check() -> None:
        deadline = time.monotonic() + timeout
        conn = psycopg2.connect(
            config.DB_URI,  # libpq accepts the postgresql:// URI as-is
            async_=1,
            application_name=f"{config.DB_CONN_NAME}-readiness",
        )
        try:
            wait(conn, deadline)
            cursor = conn.cursor()  # must outlive the async query
            cursor.execute("SELECT 1")
            wait(conn, deadline)
        finally:
            conn.close()

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
