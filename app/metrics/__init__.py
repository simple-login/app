"""Vendor neutral emission of metrics, custom events, attributes and traces.

Business code goes through the package level facade instead of talking to a
metrics vendor SDK directly::

    from app import metrics

    metrics.record_metric("Custom/postfix_incoming_queue", 12)
    metrics.record_event("AliasCreated", {"automatic": "manual"})
    metrics.set_attribute("alias_id", alias.id)

    @metrics.background_task(name="Custom/MailHandler._handle")
    def _handle(self, envelope: Envelope, msg: Message) -> Status:
        ...

The backend list is resolved once, when this package is imported, from
``app.config.METRICS_BACKENDS`` (comma separated names, ``newrelic`` by default
so historical behaviour is preserved). Several backends can be active at the
same time: they are combined with :class:`CompositeBackend`, which isolates
their failures from each other and from the caller. Adding a backend therefore
means writing a module next to this one, registering its name in
``_BACKEND_FACTORIES`` and setting a config value, without touching any call
site; the exposition side of Prometheus lives apart, in
:mod:`app.prometheus_export`.

Layout:

- :mod:`app.metrics.base`: backend protocols and errors.
- :mod:`app.metrics.noop`, :mod:`app.metrics.newrelic_backend`,
  :mod:`app.metrics.prometheus_backend`: the concrete backends.
- :mod:`app.metrics.composite`: fan out to several backends.
- this module: backend selection and the facade used by call sites.

This must stay a leaf package: it only depends on ``app.config`` and
``app.log`` so that models, jobs and API code can import it freely.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import overload

from app import config
from app.log import LOG
from app.metrics.base import (
    _P,
    _R,
    MetricsBackend,
    MetricsError,
    MetricTypeConflictError,
    Tracer,
)
from app.metrics.composite import CompositeBackend
from app.metrics.newrelic_backend import NewRelicBackend
from app.metrics.noop import NoopBackend
from app.metrics.prometheus_backend import MetricKind, PrometheusBackend

__all__ = [
    "CompositeBackend",
    "MetricKind",
    "MetricsBackend",
    "MetricTypeConflictError",
    "MetricsError",
    "NewRelicBackend",
    "NoopBackend",
    "PrometheusBackend",
    "Tracer",
    "backend_from_name",
    "background_task",
    "combine",
    "configure",
    "get_backend",
    "record_event",
    "record_metric",
    "reset",
    "set_attribute",
]


def _newrelic_backend() -> MetricsBackend:
    return NewRelicBackend()


def _noop_backend() -> MetricsBackend:
    return NoopBackend()


def _prometheus_backend() -> MetricsBackend:
    """Build the Prometheus backend for the configured exposure mode."""
    return PrometheusBackend()


_BACKEND_FACTORIES: dict[str, Callable[[], MetricsBackend]] = {
    "newrelic": _newrelic_backend,
    "noop": _noop_backend,
    "prometheus": _prometheus_backend,
}

_lock = threading.Lock()


def backend_from_name(name: str) -> MetricsBackend:
    """Build the backend registered under ``name``.

    >>> isinstance(backend_from_name("noop"), NoopBackend)
    True

    Raises:
        ValueError: if no backend is registered under that name.
    """
    factory = _BACKEND_FACTORIES.get(name)
    if factory is None:
        known_names = ", ".join(sorted(_BACKEND_FACTORIES))
        raise ValueError(
            f"Unknown metrics backend '{name}', expected one of: {known_names}"
        )

    return factory()


def combine(backends: Iterable[MetricsBackend]) -> MetricsBackend:
    """Combine ``backends`` into a single backend ready to be installed.

    Duplicated instances are dropped so a backend never receives the same
    emission twice. Zero backend yields :class:`NoopBackend`, a single backend is
    used as is and several backends are wrapped into :class:`CompositeBackend`.
    """
    unique_backends: list[MetricsBackend] = []
    seen: set[int] = set()
    for backend in backends:
        if id(backend) in seen:
            continue
        seen.add(id(backend))
        unique_backends.append(backend)

    if not unique_backends:
        return NoopBackend()
    if len(unique_backends) == 1:
        return unique_backends[0]

    return CompositeBackend(unique_backends)


def _deduplicate(names: Iterable[str]) -> list[str]:
    """Drop duplicated backend names while keeping the declared order."""
    unique_names: list[str] = []
    for name in names:
        if name not in unique_names:
            unique_names.append(name)

    return unique_names


def _build_backend_from_config() -> MetricsBackend:
    """Build the backend described by ``config.METRICS_BACKENDS``.

    An empty value means "no metrics" and yields :class:`NoopBackend`. Unknown
    names raise ``ValueError`` (propagated from :func:`backend_from_name`).
    """
    return combine(
        backend_from_name(name) for name in _deduplicate(config.METRICS_BACKENDS)
    )


def configure(backends: Sequence[MetricsBackend]) -> None:
    """Install an explicit backend list, replacing the configured one.

    Mostly useful for tests and for processes wanting a bespoke composition::

        metrics.configure([NewRelicBackend(), MyRecorder()])
    """
    _install(combine(backends))


def reset() -> None:
    """Rebuild the active backend from the config, undoing :func:`configure`."""
    _install(_build_backend_from_config())


def _install(backend: MetricsBackend) -> None:
    global _backend
    with _lock:
        _backend = backend


def get_backend() -> MetricsBackend:
    """Return the active backend."""
    return _backend


# Resolved once at import time: an invalid METRICS_BACKENDS fails fast when the
# process loads its code rather than on the first emitted metric.
_backend: MetricsBackend = _build_backend_from_config()


def record_metric(name: str, value: float) -> None:
    """Record the numeric ``value`` under ``name`` on the active backend.

    >>> record_metric("Custom/smtp_connection_time", 0.34)
    """
    get_backend().record_metric(name, value)


def record_event(event_type: str, attributes: Mapping[str, object]) -> None:
    """Record a custom event of ``event_type`` with ``attributes``.

    >>> record_event("AliasCreated", {"automatic": "manual"})
    """
    get_backend().record_event(event_type, attributes)


def set_attribute(key: str, value: object) -> None:
    """Attach ``key=value`` to the current unit of work, when supported.

    >>> set_attribute("alias_id", 42)
    """
    get_backend().set_attribute(key, value)


def _trace(
    func: Callable[_P, _R], *, name: str | None, group: str | None
) -> Callable[_P, _R]:
    """Wrap ``func`` with the active backend, or return it untouched.

    Wrapping happens once, when the decorated function is defined, so a backend
    lacking the :class:`Tracer` capability costs nothing at call time.
    """
    backend = get_backend()
    if not isinstance(backend, Tracer):
        return func

    try:
        return backend.background_task(func, name=name, group=group)
    except Exception as e:
        LOG.e(f"Traced wrapper for {func!r} could not be installed: {e}")
        return func


@overload
def background_task(func: Callable[_P, _R], /) -> Callable[_P, _R]:
    ...


@overload
def background_task(
    *, name: str | None = None, group: str | None = None
) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    ...


def background_task(
    func: Callable[_P, _R] | None = None,
    /,
    *,
    name: str | None = None,
    group: str | None = None,
) -> Callable[_P, _R] | Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    """Mark a function as a standalone unit of work to trace.

    Vendor neutral replacement for ``@newrelic.agent.background_task()``; both
    the bare and the called form are accepted::

        @metrics.background_task
        def log_failed_jobs() -> None:
            ...

        @metrics.background_task(name="Custom/alias_creation", group="Job")
        def create_alias(user_id: int) -> Alias:
            ...

    Leaving ``name`` unset lets the backend derive it from the function, which
    preserves the transaction names of the former New Relic decorators. When no
    active backend supports tracing the function is returned unchanged, so the
    decorated code behaves as if the decorator were absent.
    """
    if func is not None:
        return _trace(func, name=name, group=group)

    return functools.partial(_trace, name=name, group=group)
