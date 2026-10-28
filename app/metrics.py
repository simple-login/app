"""Vendor neutral emission of metrics, custom events, attributes and traces.

Business code goes through the module level facade instead of talking to a
metrics vendor SDK directly::

    from app import metrics

    metrics.record_metric("Custom/postfix_incoming_queue", 12)
    metrics.record_event("AliasCreated", {"automatic": "manual"})
    metrics.set_attribute("alias_id", alias.id)

    @metrics.background_task(name="Custom/MailHandler._handle")
    def _handle(self, envelope: Envelope, msg: Message) -> Status:
        ...

The backend list is resolved once, when this module is imported, from
``app.config.METRICS_BACKENDS`` (comma separated names, ``newrelic`` by default
so historical behaviour is preserved). Several backends can be active at the
same time: they are combined with :class:`CompositeBackend`, which isolates
their failures from each other and from the caller. Adding a backend later
(Prometheus) therefore means registering a name in ``_BACKEND_FACTORIES`` and
setting a config value, without touching any call site.

This must stay a leaf module: it only depends on ``app.config`` and
``app.log`` so that models, jobs and API code can import it freely.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, ParamSpec, Protocol, TypeVar, overload, runtime_checkable

from app import config
from app.log import LOG

_P = ParamSpec("_P")
_R = TypeVar("_R")


class MetricsBackend(Protocol):
    """Contract every metrics backend has to implement."""

    def record_metric(self, name: str, value: float) -> None:
        """Record a numeric value for ``name``."""
        ...

    def record_event(self, event_type: str, attributes: Mapping[str, object]) -> None:
        """Record a discrete event of type ``event_type``."""
        ...

    def set_attribute(self, key: str, value: object) -> None:
        """Attach an attribute to the current unit of work, if supported."""
        ...


@runtime_checkable
class Tracer(Protocol):
    """Optional capability: running a function as a traced unit of work.

    Kept apart from :class:`MetricsBackend` so a backend counting occurrences
    stays a valid backend without having to opt out of tracing explicitly:
    backends not implementing this protocol simply receive nothing to wrap.

    Implementations take the function to trace as an argument rather than
    being decorators themselves, so :func:`background_task` can decide when,
    and with which backends, wrapping happens.
    """

    def background_task(
        self,
        func: Callable[_P, _R],
        *,
        name: str | None = None,
        group: str | None = None,
    ) -> Callable[_P, _R]:
        """Return ``func`` wrapped into a transaction named ``name``."""
        ...


class NoopBackend:
    """Backend discarding everything.

    Used when metrics are disabled and as the neutral element of
    :class:`CompositeBackend`.
    """

    def record_metric(self, name: str, value: float) -> None:
        """Discard the metric."""

    def record_event(self, event_type: str, attributes: Mapping[str, object]) -> None:
        """Discard the event."""

    def set_attribute(self, key: str, value: object) -> None:
        """Discard the attribute."""

    def background_task(
        self,
        func: Callable[_P, _R],
        *,
        name: str | None = None,
        group: str | None = None,
    ) -> Callable[_P, _R]:
        """Return ``func`` unwrapped: nothing gets traced."""
        return func


class NewRelicBackend:
    """Backend emitting to the New Relic agent.

    Metric names, event types and attributes are forwarded unchanged so
    existing dashboards and NRQL queries keep working. Transactions started by
    :meth:`background_task` keep their historical names too, since ``name`` is
    only forwarded when set.

    ``newrelic.agent`` is imported lazily, on the first emission or on the first
    traced definition, so that this module (and everything importing it) stays
    importable in environments where the SDK is absent, tests and local tooling
    included.
    """

    def __init__(self) -> None:
        self._agent: Any = None
        self._import_failed = False

    def _get_agent(self) -> Any:
        if self._agent is None and not self._import_failed:
            try:
                from newrelic import agent
            except ImportError as e:
                # Only reported once to avoid flooding the logs when every call
                # site tries to emit.
                self._import_failed = True
                LOG.e(f"newrelic is not importable, metrics are dropped: {e}")
                return None
            self._agent = agent

        return self._agent

    def record_metric(self, name: str, value: float) -> None:
        """Forward the metric to ``newrelic.agent.record_custom_metric``."""
        agent = self._get_agent()
        if agent is not None:
            agent.record_custom_metric(name, value)

    def record_event(self, event_type: str, attributes: Mapping[str, object]) -> None:
        """Forward the event to ``newrelic.agent.record_custom_event``."""
        agent = self._get_agent()
        if agent is not None:
            agent.record_custom_event(event_type, dict(attributes))

    def set_attribute(self, key: str, value: object) -> None:
        """Forward the attribute to ``newrelic.agent.add_custom_attribute``."""
        agent = self._get_agent()
        if agent is not None:
            agent.add_custom_attribute(key, value)

    def background_task(
        self,
        func: Callable[_P, _R],
        *,
        name: str | None = None,
        group: str | None = None,
    ) -> Callable[_P, _R]:
        """Wrap ``func`` into ``newrelic.agent.background_task``.

        When ``name`` is omitted the agent derives it from ``func``, which is
        what the historical ``@newrelic.agent.background_task()`` usages did.
        """
        agent = self._get_agent()
        if agent is None:
            return func

        wrapped: Callable[_P, _R] = agent.background_task(name=name, group=group)(func)
        return wrapped


class CompositeBackend:
    """Fan out to several backends, isolating their failures.

    An exception raised by one backend is logged and swallowed so that it can
    neither prevent the other backends from receiving the emission nor reach
    the caller: emitting a metric must never break the business flow.
    """

    def __init__(self, backends: Sequence[MetricsBackend]) -> None:
        self._backends: tuple[MetricsBackend, ...] = tuple(backends)

    @property
    def backends(self) -> tuple[MetricsBackend, ...]:
        """The combined backends, in emission order."""
        return self._backends

    def record_metric(self, name: str, value: float) -> None:
        """Fan out a metric."""
        for backend in self._backends:
            self._run(backend, "record_metric", name, value)

    def record_event(self, event_type: str, attributes: Mapping[str, object]) -> None:
        """Fan out an event."""
        for backend in self._backends:
            self._run(backend, "record_event", event_type, attributes)

    def set_attribute(self, key: str, value: object) -> None:
        """Fan out an attribute."""
        for backend in self._backends:
            self._run(backend, "set_attribute", key, value)

    def background_task(
        self,
        func: Callable[_P, _R],
        *,
        name: str | None = None,
        group: str | None = None,
    ) -> Callable[_P, _R]:
        """Chain the tracers among the backends around ``func``.

        Backends without the :class:`Tracer` capability are skipped, so mixing
        a tracing backend with a plain counter backend stays valid. A backend
        failing to wrap is logged and skipped rather than propagated: tracing
        must not be able to break decorating at import time.
        """
        wrapped = func
        for backend in self._backends:
            if not isinstance(backend, Tracer):
                continue
            try:
                wrapped = backend.background_task(wrapped, name=name, group=group)
            except Exception as e:
                LOG.e(
                    f"Metrics backend {type(backend).__name__}.background_task "
                    f"failed: {e}"
                )

        return wrapped

    def _run(self, backend: MetricsBackend, action: str, *args: object) -> None:
        try:
            method: Callable[..., None] = getattr(backend, action)
            method(*args)
        except Exception as e:
            # Deliberately broad: third party clients raise whatever they like
            # (network, serialisation, closed client...) and none of it is the
            # caller's problem. LOG.e logs the traceback.
            LOG.e(f"Metrics backend {type(backend).__name__}.{action} failed: {e}")


def _newrelic_backend() -> MetricsBackend:
    return NewRelicBackend()


def _noop_backend() -> MetricsBackend:
    return NoopBackend()


_BACKEND_FACTORIES: dict[str, Callable[[], MetricsBackend]] = {
    "newrelic": _newrelic_backend,
    "noop": _noop_backend,
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
