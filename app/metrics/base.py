"""Contracts and errors shared by every metrics backend."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import ParamSpec, Protocol, TypeVar, runtime_checkable

_P = ParamSpec("_P")
_R = TypeVar("_R")


class MetricsError(Exception):
    """Base class for the metrics errors raised on purpose."""


class MetricTypeConflictError(MetricsError):
    """Raised when one metric name is used with conflicting definitions.

    A Prometheus metric name is bound, for the whole life of the process, to a
    single instrument kind and a single label set. Emitting
    ``Custom/nb_rcpt_tos`` as a gauge and then as a histogram cannot be
    represented, so it is reported instead of being silently coalesced.

    Attributes:
        name: the offending metric name, already sanitized.
        reason: human readable explanation of the clash.
    """

    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"Metric '{name}' {reason}")
        self.name = name
        self.reason = reason


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
    being decorators themselves, so :func:`app.metrics.background_task` can
    decide when, and with which backends, wrapping happens.
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
