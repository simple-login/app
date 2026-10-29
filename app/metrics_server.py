import threading
from dataclasses import dataclass
from typing import Optional

from flask import Flask, Response
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from werkzeug.serving import BaseWSGIServer, make_server

from app import config
from app.log import LOG

_process_info = Gauge(
    "sl_process_info", "Constant 1, labelled with the running service", ["service"]
)


def create_metrics_app() -> Flask:
    """Minimal Flask app serving the default Prometheus registry. No DB access."""
    app = Flask(__name__)

    @app.route("/metrics", methods=["GET"])
    def metrics():
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
    try:
        server = make_server(host, port, create_metrics_app(), threaded=True)
    except (OSError, OverflowError) as e:
        # OSError: port in use (expected, e.g. several processes on one host).
        # OverflowError: port outside 0-65535.
        LOG.w("Cannot start metrics server on %s:%s: %s", host, port, e)
        return None

    _process_info.labels(service=service_name).set(1)
    thread = threading.Thread(
        target=server.serve_forever, name="metrics-server", daemon=True
    )
    thread.start()
    LOG.i("Metrics server for %s listening on %s:%s", service_name, host, port)
    return MetricsServer(server=server, thread=thread)


def start_metrics_server_from_config(service_name: str) -> Optional[MetricsServer]:
    """Start the metrics server only if METRICS_SERVER_PORT is set."""
    if config.METRICS_SERVER_PORT is None:
        return None
    return start_metrics_server(
        config.METRICS_SERVER_HOST, config.METRICS_SERVER_PORT, service_name
    )
