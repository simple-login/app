import threading
from dataclasses import dataclass
from typing import Optional

from flask import Flask, Response, request
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from werkzeug.serving import BaseWSGIServer, make_server

from app import config
from app.log import LOG
from app.prometheus_export import is_auth_valid


def create_metrics_app() -> Flask:
    """Minimal Flask app serving the default Prometheus registry. No DB access.

    Like the web app, /metrics is only registered when PROMETHEUS_METRICS_TOKEN is
    set, and requires it as a bearer token.
    """
    app = Flask(__name__)

    if not config.PROMETHEUS_METRICS_TOKEN:
        LOG.e("PROMETHEUS_METRICS_TOKEN is empty: the /metrics endpoint stays disabled")
        return app

    @app.route("/metrics", methods=["GET"])
    def metrics():
        if not is_auth_valid(request.headers.get("Authorization")):
            return Response(
                "", 401, headers={"WWW-Authenticate": 'Bearer realm="metrics"'}
            )
        return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

    return app


@dataclass
class MetricsServer:
    server: BaseWSGIServer
    thread: threading.Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_metrics_server(
    host: str, port: int, service_name: str
) -> Optional[MetricsServer]:
    """Serve /metrics from a daemon thread so the calling process is never blocked.

    Returns None (after logging) if the port cannot be bound: metrics must never
    prevent the real work of the process.
    """
    if not 1 <= port <= 65535:
        # Checked here because on Linux the kernel silently truncates the port to
        # 16 bits (70000 -> 4464, 65616 -> 80) instead of raising.
        LOG.w("Cannot start metrics server: port %s is outside 1-65535", port)
        return None

    try:
        server = make_server(host, port, create_metrics_app(), threaded=True)
    except OSError as e:
        # Port in use (expected, e.g. several processes on one host).
        LOG.w("Cannot start metrics server on %s:%s: %s", host, port, e)
        return None

    thread = threading.Thread(
        target=server.serve_forever, name="metrics-server", daemon=True
    )
    thread.start()
    LOG.i("Metrics server for %s listening on %s:%s", service_name, host, port)
    return MetricsServer(server=server, thread=thread)


def start_metrics_server_from_config(service_name: str) -> Optional[MetricsServer]:
    """Start the metrics server if METRICS_SERVER_PORT is set.

    When it is not, log an error and return None: callers need no guard and the
    process is never stopped by a missing metrics configuration.
    """
    if config.METRICS_SERVER_PORT is None:
        LOG.e("Prometheus metrics are not enabled: METRICS_SERVER_PORT is not set")
        return None
    return start_metrics_server(
        config.METRICS_SERVER_HOST, config.METRICS_SERVER_PORT, service_name
    )
