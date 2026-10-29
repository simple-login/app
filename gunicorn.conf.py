"""Gunicorn configuration, loaded automatically by ``gunicorn`` from the CWD.

Only the Prometheus bookkeeping lives here; every other setting keeps coming
from the command line in the Dockerfile ``CMD``.

Multiprocess mode is always on when the Prometheus backend is enabled: the
workers write their metrics to ``PROMETHEUS_MULTIPROC_DIR``, or to a temporary
directory created here when it is unset, and the scrape aggregates them.
Without it each worker would keep its own in-memory registry, exposing a
fraction of the traffic.

Whichever worker answers ``GET /metrics`` serves the aggregate of every
worker's files. Three hooks are enough:

``on_starting``
    The master empties the shared directory before the first fork.

``child_exit``
    A recycled worker hands back its live-gauge files.

``on_exit``
    The master removes the temporary directory, if it created one.

See https://prometheus.github.io/client_python/multiprocess/ for the protocol.
"""

from __future__ import annotations

from typing import Any

# Imported under an underscore name on purpose: gunicorn reads this module's
# globals as setting overrides, and a bare ``config`` would be handed to the
# ``config`` setting, which then rejects the module as "Not a string".
from app import config as _app_config

import os as _os
import shutil as _shutil
import tempfile as _tempfile

# Without a shared directory every worker keeps a private registry, so a scrape
# would only report the share of the worker answering it. Multiprocess mode is therefore mandatory under
# gunicorn, and a temporary directory stands in when none is configured. This
# must happen before prometheus_client is imported below, as the library picks
# its storage from the environment at import time; the workers are forked from
# this process and inherit both the environment and the config value.
_owned_multiproc_dir: str | None = None
if "prometheus" in _app_config.METRICS_BACKENDS:
    if not _app_config.PROMETHEUS_MULTIPROC_DIR:
        _owned_multiproc_dir = _tempfile.mkdtemp(prefix="prometheus-multiproc-")
        _app_config.PROMETHEUS_MULTIPROC_DIR = _owned_multiproc_dir
    _os.environ["PROMETHEUS_MULTIPROC_DIR"] = _app_config.PROMETHEUS_MULTIPROC_DIR

try:
    from app.prometheus_export import (
        mark_worker_dead,
        populate_multiproc_dir,
    )
except ImportError:  # pragma: no cover - gunicorn must start even if app fails
    mark_worker_dead = None  # type: ignore[assignment]
    populate_multiproc_dir = None  # type: ignore[assignment]


def _multiproc_enabled() -> bool:
    """Whether the metrics have to survive the fork of the workers."""
    return (
        bool(_app_config.PROMETHEUS_MULTIPROC_DIR)
        and "prometheus" in _app_config.METRICS_BACKENDS
    )


def on_starting(server: Any) -> None:
    """Empty the shared directory before any worker exists.

    Runs in the master, before the first fork. Stale ``.db`` files from a
    previous generation would otherwise be inherited by the new workers and
    counted for the lifetime of the deployment. Only the master may do this:
    a worker wiping the directory would erase what its siblings are writing.
    """
    if not _multiproc_enabled() or populate_multiproc_dir is None:
        return

    populate_multiproc_dir()
    server.log.info("Prometheus multiprocess mode enabled")


def child_exit(server: Any, worker: Any) -> None:
    """Drop the metric files of an exiting worker.

    Prometheus sums every ``.db`` file it finds, so a file left behind by a
    recycled worker keeps contributing its last counter values forever.
    """
    if not _multiproc_enabled() or mark_worker_dead is None:
        return

    mark_worker_dead(worker.pid)
    server.log.info("Released the Prometheus files of worker pid %s", worker.pid)


def on_exit(server: Any) -> None:
    """Remove the temporary multiprocess directory, if one was created.

    A configured ``PROMETHEUS_MULTIPROC_DIR`` is left in place: it may be a
    volume owned by someone else, and ``on_starting`` empties it anyway.
    """
    if _owned_multiproc_dir is None:
        return

    _shutil.rmtree(_owned_multiproc_dir, ignore_errors=True)
