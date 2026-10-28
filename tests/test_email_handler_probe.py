import smtplib
import socket
import threading
import time
from typing import Callable, Iterator, List

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Sink

from app.email_probe import (
    HEALTH_ADDRESS,
    HEALTH_OK,
    READY_ADDRESS,
    READY_OK,
    ReadinessChecker,
    database_check,
)
from email_handler import MailHandler
from scripts.smtp_probe import probe


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


def test_default_readiness_checks_database(flask_client):
    # real DB reachable via its own connection
    database_check(timeout=2)()


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
