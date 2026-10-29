import asyncio
import smtplib
import socket
import threading
import time
from typing import Callable, Iterator, List
from urllib.parse import urlsplit

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Sink
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import ProgrammingError

from app import config
from app.db import Session
from app.email_probe import (
    HEALTH_OK,
    READY_OK,
    ReadinessChecker,
    database_check,
)
from email_handler import MailHandler
from scripts.smtp_probe import probe

HEALTH_ADDRESS = config.EMAIL_HANDLER_HEALTH_ADDRESS
READY_ADDRESS = config.EMAIL_HANDLER_READY_ADDRESS


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RecordingHandler(MailHandler):
    """MailHandler whose DATA stage only records the envelope recipients."""

    def __init__(self, readiness: Callable[[], None]) -> None:
        super().__init__(readiness=ReadinessChecker(readiness, timeout=0.5))
        self.delivered: List[List[str]] = []

    async def handle_DATA(self, server, session, envelope):
        self.delivered.append(list(envelope.rcpt_tos))
        return "250 OK"


def _start(handler) -> Iterator[Controller]:
    port = _free_port()
    controller = Controller(handler, hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield controller
    finally:
        controller.stop()


@pytest.fixture
def ready_handler() -> RecordingHandler:
    return RecordingHandler(lambda: None)


@pytest.fixture
def controller(ready_handler) -> Iterator[Controller]:
    yield from _start(ready_handler)


def _rcpt(controller: Controller, address: str):
    with smtplib.SMTP(controller.hostname, controller.port, timeout=5) as smtp:
        smtp.ehlo()
        smtp.mail("<>")
        return smtp.docmd("RCPT", f"TO:<{address}>")


def test_health_probe_replies_with_marker(controller):
    assert _rcpt(controller, HEALTH_ADDRESS) == (250, HEALTH_OK[4:].encode())


def test_probe_address_is_case_insensitive(controller):
    assert _rcpt(controller, HEALTH_ADDRESS.upper()) == (250, HEALTH_OK[4:].encode())


def test_ready_probe_replies_with_marker(controller):
    assert _rcpt(controller, READY_ADDRESS) == (250, READY_OK[4:].encode())


def test_probe_replies_are_distinct():
    assert HEALTH_OK != READY_OK


def test_probe_is_not_added_to_rcpt_tos(controller, ready_handler):
    with smtplib.SMTP(controller.hostname, controller.port, timeout=5) as smtp:
        smtp.ehlo()
        smtp.mail("a@example.com")
        assert smtp.rcpt(HEALTH_ADDRESS)[0] == 250
        assert smtp.rcpt("real@example.com")[0] == 250
        assert smtp.rcpt(READY_ADDRESS)[0] == 250
        smtp.data("Subject: x\r\n\r\nbody\r\n")
    assert ready_handler.delivered == [["real@example.com"]]


def test_rset_then_normal_mail(controller, ready_handler):
    with smtplib.SMTP(controller.hostname, controller.port, timeout=5) as smtp:
        smtp.ehlo()
        smtp.mail("a@example.com")
        smtp.rcpt(HEALTH_ADDRESS)
        smtp.rset()
        smtp.mail("a@example.com")
        smtp.rcpt("real@example.com")
        smtp.data("Subject: x\r\n\r\nbody\r\n")
    assert ready_handler.delivered == [["real@example.com"]]


def test_probe_only_session_does_not_deliver(controller, ready_handler):
    _rcpt(controller, HEALTH_ADDRESS)
    assert ready_handler.delivered == []


def test_ready_fails_when_check_raises():
    def broken() -> None:
        raise RuntimeError("db down")

    for controller in _start(RecordingHandler(broken)):
        code, _ = _rcpt(controller, READY_ADDRESS)
        assert code == 451
        # health is independent of readiness
        assert _rcpt(controller, HEALTH_ADDRESS) == (250, HEALTH_OK[4:].encode())


def test_ready_times_out_on_stalled_check_and_health_keeps_answering():
    release = threading.Event()

    def stalled() -> None:
        release.wait(10)

    handler = RecordingHandler(stalled)
    try:
        for controller in _start(handler):
            start = time.monotonic()
            code, _ = _rcpt(controller, READY_ADDRESS)
            assert code == 451
            assert time.monotonic() - start < 3
            # the stalled check is still outstanding: no new one is started
            start = time.monotonic()
            assert _rcpt(controller, READY_ADDRESS)[0] == 451
            assert time.monotonic() - start < 0.4
            assert _rcpt(controller, HEALTH_ADDRESS) == (250, HEALTH_OK[4:].encode())
    finally:
        release.set()


def test_ready_recovers_after_stall():
    release = threading.Event()
    state = {"stall": True}

    def check() -> None:
        if state["stall"]:
            release.wait(10)

    for controller in _start(RecordingHandler(check)):
        assert _rcpt(controller, READY_ADDRESS)[0] == 451
        state["stall"] = False
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if _rcpt(controller, READY_ADDRESS) == (250, READY_OK[4:].encode()):
                return
            time.sleep(0.1)
        pytest.fail("readiness did not recover")


# --- default readiness check: the app's own Session / pooled engine ----------


@pytest.fixture
def app_engine(flask_client, monkeypatch) -> Iterator[Callable[..., Engine]]:
    """Point ``app.db.Session`` at a throwaway engine (pooled, like production)."""
    engines: List[Engine] = []

    def make(url: str = config.DB_URI, **pool_kwargs) -> Engine:
        engine = create_engine(url, **pool_kwargs)
        engines.append(engine)
        monkeypatch.setitem(Session.session_factory.kw, "bind", engine)
        Session.remove()
        return engine

    yield make
    Session.remove()
    for engine in engines:
        engine.dispose()


def _default_ready_reply():
    # MailHandler() wires the production readiness check
    for controller in _start(MailHandler()):
        return _rcpt(controller, READY_ADDRESS)


def test_default_readiness_ok_on_healthy_pool(app_engine):
    app_engine(pool_size=1, max_overflow=0)
    assert _default_ready_reply() == (250, READY_OK[4:].encode())


def test_default_readiness_fails_when_pool_exhausted(app_engine):
    engine = app_engine(pool_size=1, max_overflow=1, pool_timeout=0.1)
    held = [engine.connect(), engine.connect()]  # pool and overflow both in use
    try:
        assert _default_ready_reply()[0] == 451
    finally:
        for connection in held:
            connection.close()


def test_default_readiness_fails_when_pool_is_starved(app_engine):
    engine = app_engine(pool_size=1, max_overflow=0, pool_timeout=0.1)
    held = engine.connect()  # the only connection is already checked out
    try:
        assert _default_ready_reply()[0] == 451
    finally:
        held.close()


def test_default_readiness_fails_when_engine_backend_is_dead(app_engine):
    dead = urlsplit(config.DB_URI)._replace(
        netloc=f"test:test@127.0.0.1:{_free_port()}"
    )
    app_engine(dead.geturl(), pool_pre_ping=True)
    assert _default_ready_reply()[0] == 451


def test_default_readiness_fails_when_session_is_wedged(app_engine):
    connection = app_engine().connect()
    transaction = connection.begin()
    with pytest.raises(ProgrammingError):
        connection.execute(text("SELECT * FROM no_such_table"))
    # the transaction is aborted: InFailedSqlTransaction until rollback
    Session.configure(bind=connection)
    try:
        assert _default_ready_reply()[0] == 451
    finally:
        transaction.rollback()
        connection.close()


def test_default_readiness_is_bounded_when_pool_waits_and_then_recovers(app_engine):
    # pool_timeout far exceeds the readiness deadline: the worker keeps waiting
    # for a connection after the reply has been given
    engine = app_engine(pool_size=1, max_overflow=0, pool_timeout=30)
    held = engine.connect()
    checker = ReadinessChecker(database_check, timeout=0.5)

    start = time.monotonic()
    assert asyncio.run(checker.is_ready()) is False
    assert time.monotonic() - start < 2

    held.close()  # the waiting worker gets the connection and finishes
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if asyncio.run(checker.is_ready()):
            return
        time.sleep(0.1)
    pytest.fail("readiness did not recover once the pool had a free connection")


# --- scripts/smtp_probe.py -------------------------------------------------


def test_probe_script_succeeds_on_marker(controller):
    assert probe("health", controller.hostname, controller.port, 5) == 0
    assert probe("ready", controller.hostname, controller.port, 5) == 0


def test_probe_script_fails_on_plain_250_without_marker():
    for controller in _start_sink():
        assert probe("health", controller.hostname, controller.port, 5) != 0
        assert probe("ready", controller.hostname, controller.port, 5) != 0


def test_probe_script_fails_when_ready_check_fails():
    def broken() -> None:
        raise RuntimeError("db down")

    for controller in _start(RecordingHandler(broken)):
        assert probe("ready", controller.hostname, controller.port, 5) != 0
        assert probe("health", controller.hostname, controller.port, 5) == 0


def test_probe_script_fails_when_nothing_listens():
    assert probe("health", "127.0.0.1", _free_port(), 1) != 0


def _start_sink() -> Iterator[Controller]:
    yield from _start(Sink())


def test_probe_addresses_default_to_probe_invalid():
    assert HEALTH_ADDRESS == "health@probe.invalid"
    assert READY_ADDRESS == "ready@probe.invalid"


def test_probe_addresses_are_configurable(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_HANDLER_HEALTH_ADDRESS", "H@Custom.Test")
    monkeypatch.setattr(config, "EMAIL_HANDLER_READY_ADDRESS", "r@custom.test")
    handler = RecordingHandler(lambda: None)
    for controller in _start(handler):
        assert _rcpt(controller, "h@custom.test") == (250, HEALTH_OK[4:].encode())
        assert _rcpt(controller, "r@custom.test") == (250, READY_OK[4:].encode())
        # the defaults are no longer special: treated as ordinary recipients
        with smtplib.SMTP(controller.hostname, controller.port, timeout=5) as smtp:
            smtp.ehlo()
            smtp.mail("a@example.com")
            assert smtp.rcpt(HEALTH_ADDRESS)[0] == 250
            smtp.data("Subject: x\r\n\r\nbody\r\n")
        assert handler.delivered == [[HEALTH_ADDRESS]]
