import socket
import threading
import urllib.request

from app import config
from app.metrics_server import start_metrics_server, start_metrics_server_from_config


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(port: int, path: str) -> tuple[int, str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return r.status, r.read().decode()


def test_serves_prometheus_metrics_in_background_thread():
    port = _free_port()
    server = start_metrics_server("127.0.0.1", port, service_name="unit_test")
    try:
        assert server.thread.daemon  # never keeps the process alive
        assert server.thread is not threading.current_thread()
        status, body = _get(port, "/metrics")
        assert status == 200
        assert 'sl_process_info{service="unit_test"} 1.0' in body
    finally:
        server.stop()


def test_not_started_when_port_not_configured(monkeypatch):
    monkeypatch.setattr(config, "METRICS_SERVER_PORT", None)
    assert start_metrics_server_from_config("unit_test") is None


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


def test_bind_failure_does_not_raise(monkeypatch):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        monkeypatch.setattr(config, "METRICS_SERVER_PORT", port)
        monkeypatch.setattr(config, "METRICS_SERVER_HOST", "127.0.0.1")
        assert start_metrics_server_from_config("unit_test") is None
