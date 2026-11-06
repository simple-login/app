import socket
import threading
import urllib.error
import urllib.request

import pytest

from app import config, metrics_server
from app.log import LOG
from app.metrics_server import start_metrics_server, start_metrics_server_from_config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


TOKEN = "s3cret"


@pytest.fixture(autouse=True)
def metrics_token(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", TOKEN)


def _get(port: int, path: str, token: str | None = TOKEN) -> tuple[int, str]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_serves_prometheus_metrics_in_background_thread():
    port = _free_port()
    server = start_metrics_server("127.0.0.1", port, service_name="unit_test")
    assert server is not None
    try:
        assert server.thread.daemon  # never keeps the process alive
        assert server.thread is not threading.current_thread()
        status, body = _get(port, "/metrics")
        assert status == 200
        assert "sl_process_info" not in body
    finally:
        server.stop()


@pytest.mark.parametrize("token", [None, "wrong", ""])
def test_rejects_missing_or_wrong_bearer_token(token):
    port = _free_port()
    server = start_metrics_server("127.0.0.1", port, service_name="unit_test")
    assert server is not None
    try:
        assert _get(port, "/metrics", token=token)[0] == 401
    finally:
        server.stop()


def test_metrics_route_not_registered_without_token(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", None)
    errors = []
    monkeypatch.setattr(LOG, "e", lambda *a, **k: errors.append(a))
    port = _free_port()
    server = start_metrics_server("127.0.0.1", port, service_name="unit_test")
    assert server is not None
    try:
        assert _get(port, "/metrics")[0] == 404
    finally:
        server.stop()
    assert len(errors) == 1


def test_disabled_metrics_log_error_and_do_not_raise(monkeypatch):
    monkeypatch.setattr(config, "METRICS_SERVER_PORT", None)
    errors = []
    monkeypatch.setattr(LOG, "e", lambda *a, **k: errors.append(a))
    assert start_metrics_server_from_config("unit_test") is None
    assert len(errors) == 1


def test_started_from_config(monkeypatch):
    port = _free_port()
    monkeypatch.setattr(config, "METRICS_SERVER_PORT", port)
    monkeypatch.setattr(config, "METRICS_SERVER_HOST", "127.0.0.1")
    server = start_metrics_server_from_config("unit_test")
    assert server is not None
    try:
        assert _get(port, "/metrics")[0] == 200
    finally:
        server.stop()


def test_bind_failure_logs_warning_and_returns_none(monkeypatch):
    warnings = []
    errors = []
    monkeypatch.setattr(LOG, "w", lambda *a, **k: warnings.append(a))
    monkeypatch.setattr(LOG, "e", lambda *a, **k: errors.append(a))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr(config, "METRICS_SERVER_PORT", port)
        monkeypatch.setattr(config, "METRICS_SERVER_HOST", "127.0.0.1")
        assert start_metrics_server_from_config("unit_test") is None
    assert len(warnings) == 1
    assert errors == []  # LOG.e would raise a Sentry event with a traceback


def test_out_of_range_port_does_not_raise(monkeypatch):
    monkeypatch.setattr(config, "METRICS_SERVER_PORT", 70000)
    monkeypatch.setattr(config, "METRICS_SERVER_HOST", "127.0.0.1")
    assert start_metrics_server_from_config("unit_test") is None


@pytest.mark.parametrize("port", [-1, 0, 65536, 65616, 70000])
def test_out_of_range_port_never_reaches_the_socket_layer(monkeypatch, port):
    # On Linux the kernel silently truncates the port to 16 bits
    # (70000 -> 4464, 65616 -> 80), so the range must be checked before binding.
    def fail_make_server(*args, **kwargs):
        raise AssertionError("make_server must not be called for an invalid port")

    monkeypatch.setattr(metrics_server, "make_server", fail_make_server)
    warnings = []
    monkeypatch.setattr(LOG, "w", lambda *a, **k: warnings.append(a))
    assert start_metrics_server("127.0.0.1", port, service_name="unit_test") is None
    assert len(warnings) == 1
