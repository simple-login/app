"""Backend fanning out to several backends."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from app.log import LOG
from app.metrics.base import _P, _R, MetricsBackend, Tracer


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
