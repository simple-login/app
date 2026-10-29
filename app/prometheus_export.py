"""Exposition of the Prometheus metrics: the ``/metrics`` view of the web app.

Kept apart from :mod:`app.metrics` on purpose. ``app.metrics`` is a leaf module
imported by models, jobs and API code; the code below pulls in a web framework
and the exposition format, so importing it eagerly would drag those
dependencies into every process.

When the Prometheus backend is enabled, the web app serves ``GET /metrics`` on
its own Flask server, protected by a bearer token, see
:func:`create_metrics_blueprint`. Under gunicorn the payload aggregates the
mmapped files every worker writes, so whichever worker answers the scrape
reports the whole traffic.

Emptying the shared multiprocess directory is the master's job
(``on_starting`` -> :func:`prepare_multiproc_dir`): a worker must never delete
the files its siblings are still writing, so :func:`setup_prometheus` only
checks that the directory reached the workers' environment.

Nothing here runs at import time: :func:`setup_prometheus` is called explicitly
by the entry points, so importing this module is free.
"""

from __future__ import annotations

import hmac
import os

from app import config
from app.log import LOG

from flask import Blueprint, Flask, Response
from prometheus_client import CollectorRegistry

METRICS_PATH = "/metrics"

_AUTHORIZATION_HEADER = "Authorization"
_BEARER_PREFIX = "Bearer "


def prometheus_enabled() -> bool:
    """Whether the Prometheus backend is selected in ``METRICS_BACKENDS``.

    >>> prometheus_enabled() == ("prometheus" in config.METRICS_BACKENDS)
    True
    """
    return "prometheus" in config.METRICS_BACKENDS


def prepare_multiproc_dir(directory: str | None = None) -> str | None:
    """Empty the multiprocess directory that the gunicorn workers share.

    Must run once, in the master process, before the workers fork: a stale
    ``.db`` file left by a previous run makes every worker inherit counters that
    no longer correspond to anything, and Prometheus would report inflated
    totals for the lifetime of the deployment.

    Args:
        directory: defaults to ``config.PROMETHEUS_MULTIPROC_DIR``.

    Returns:
        The prepared directory, or ``None`` when multiprocess mode is off.
    """
    target = directory if directory is not None else config.PROMETHEUS_MULTIPROC_DIR
    if not target:
        return None

    if os.path.isdir(target):
        # Only the metric files are cleared; the directory itself may be a
        # docker volume owned by someone else, so recreating it is avoided.
        for entry in os.listdir(target):
            if not entry.endswith(".db"):
                continue
            path = os.path.join(target, entry)
            try:
                os.unlink(path)
            except OSError as e:
                LOG.w(f"Could not remove stale metrics file {path}: {e}")
    else:
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as e:
            LOG.e(f"Could not create {target}, multiprocess mode is unusable: {e}")
            return None

    LOG.i(f"Prepared the Prometheus multiprocess directory {target}")
    return target


def populate_multiproc_dir(directory: str | None = None) -> None:
    """Call :func:`prepare_multiproc_dir` and apply it to the client library.

    The library reads ``PROMETHEUS_MULTIPROC_DIR`` from the environment when its
    values module is imported, hence setting the variable here rather than
    trusting the operator to have exported it. Gunicorn workers inherit the
    environment of the master, so running this in ``on_starting`` is enough for
    all of them; a worker must never call it, as emptying the directory would
    destroy the data its siblings keep appending to.
    """
    target = prepare_multiproc_dir(directory)
    if target is None:
        return

    os.environ["PROMETHEUS_MULTIPROC_DIR"] = target


def ensure_multiproc_env() -> bool:
    """Check that the worker inherited the multiprocess directory.

    ``prometheus_client`` reads ``PROMETHEUS_MULTIPROC_DIR`` from ``os.environ``
    when it is imported, so setting ``config.PROMETHEUS_MULTIPROC_DIR`` after
    the fact has no effect. Rather than silently going without the shared
    files, report it: a worker exposing its own private registry would look
    healthy while reporting a fraction of the traffic.

    Returns:
        ``True`` when multiprocess mode is off or properly wired.
    """
    if not config.PROMETHEUS_MULTIPROC_DIR:
        return True

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR") == config.PROMETHEUS_MULTIPROC_DIR:
        return True

    LOG.e(
        "PROMETHEUS_MULTIPROC_DIR is set but was not exported before importing "
        "prometheus_client: the workers will not share their metrics. Start the "
        "web app through gunicorn so that on_starting prepares it, or export the "
        "variable yourself."
    )
    return False


def mark_worker_dead(pid: int) -> None:
    """Clean up the metric files a finished gunicorn worker left behind.

    Called from the ``child_exit`` gunicorn hook declared in ``gunicorn.conf.py``.
    The library drops the worker's live-gauge files so a recycled worker stops
    contributing its last reading to every future scrape. Counters are left in
    place on purpose: they are cumulative, and removing them would restart the
    totals at zero on every worker recycle.

    Args:
        pid: pid of the worker that just exited.
    """
    directory = config.PROMETHEUS_MULTIPROC_DIR
    if not directory:
        return

    try:
        from prometheus_client import multiprocess
    except ImportError as e:
        LOG.e(f"prometheus_client is not importable, cannot drop the pid {pid}: {e}")
        return

    multiprocess.mark_process_dead(pid, path=directory)


def _multiproc_registry(directory: str) -> CollectorRegistry:
    """Build a registry aggregating every `.db` file found in ``directory``.

    The files are merged at collection time, not at import time, so workers
    started or recycled after this call are taken into account.

    Args:
        directory: the shared ``PROMETHEUS_MULTIPROC_DIR``.

    Returns:
        A registry whose only collector is the ``MultiProcessCollector``.
    """
    from prometheus_client import CollectorRegistry
    from prometheus_client.multiprocess import MultiProcessCollector

    registry = CollectorRegistry()
    MultiProcessCollector(registry, path=directory)
    return registry


def metrics_payload() -> tuple[bytes, str]:
    """Render the current metrics in the text exposition format.

    Uses ``MultiProcessCollector`` when multiprocess mode is active, so the
    payload aggregates every live worker, and the default registry otherwise.

    Returns:
        The body and its content type, ready for a WSGI response.
    """
    from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

    directory = config.PROMETHEUS_MULTIPROC_DIR
    if directory:
        return generate_latest(_multiproc_registry(directory)), CONTENT_TYPE_LATEST

    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def is_auth_valid(authorization_header: str | None) -> bool:
    """Validate an ``Authorization: Bearer <token>`` header in constant time.

    The comparison goes through :func:`hmac.compare_digest` so that timing a
    series of requests reveals nothing about the expected token's prefix.

    Args:
        authorization_header: raw header value, or ``None`` when absent.

    Returns:
        ``True`` only when the header carries the configured token.

    >>> is_auth_valid(f"Bearer {config.PROMETHEUS_METRICS_TOKEN}")  # doctest: +SKIP
    True
    >>> is_auth_valid(None)
    False
    """
    expected = config.PROMETHEUS_METRICS_TOKEN
    if not expected or not authorization_header:
        # Refuse to authenticate when no token is configured: an endpoint that
        # accepts everything is worse than one that is absent.
        return False

    if not authorization_header.startswith(_BEARER_PREFIX):
        return False

    provided = authorization_header[len(_BEARER_PREFIX) :]
    return hmac.compare_digest(provided, expected)


def create_metrics_blueprint() -> Blueprint | None:
    """Build the ``/metrics`` blueprint, or ``None`` when it is not wanted.

    Registered only when a token is configured, so a misconfiguration disables
    the route instead of opening it. The view is excluded from rate limiting
    and from the session machinery: it sets no cookie, requires no login and
    has no CSRF token because a scraper is not a browser.

    Returns:
        The configured blueprint, or ``None``.
    """
    if not config.PROMETHEUS_METRICS_TOKEN:
        LOG.e(
            "Prometheus is enabled but PROMETHEUS_METRICS_TOKEN is empty: the "
            "/metrics endpoint stays disabled"
        )
        return None

    from flask import Blueprint

    blueprint = Blueprint("prometheus_metrics", __name__)

    @blueprint.route(METRICS_PATH, methods=["GET"])
    def metrics_view() -> tuple[str, int, dict[str, str]] | Response:
        """Return the exposition, after checking the bearer token."""
        from flask import request

        if not is_auth_valid(request.headers.get(_AUTHORIZATION_HEADER)):
            return "", 401, {"WWW-Authenticate": 'Bearer realm="metrics"'}

        body, content_type = metrics_payload()
        return body.decode("utf-8"), 200, {"Content-Type": content_type}

    from app.extensions import limiter

    # A scraper polls every few seconds from one address; rate limiting it would
    # only ever produce 429s in the middle of the metric stream.
    limiter.exempt(blueprint)

    return blueprint


def setup_prometheus(app: Flask) -> None:
    """Register the ``/metrics`` endpoint on ``app`` when Prometheus is enabled.

    Emptying ``PROMETHEUS_MULTIPROC_DIR`` is deliberately *not* done here: it
    belongs to the gunicorn master's ``on_starting`` hook, before any fork. A
    worker calling this must leave the files of its siblings alone.

    Args:
        app: the Flask app. The blueprint is registered on it explicitly rather
            than through ``current_app``, so this works in the application
            factory where no app context is pushed yet.
    """
    if not prometheus_enabled():
        return

    ensure_multiproc_env()

    blueprint = create_metrics_blueprint()
    if blueprint is not None:
        app.register_blueprint(blueprint)
        LOG.i(f"Exposing Prometheus metrics on {METRICS_PATH}")
