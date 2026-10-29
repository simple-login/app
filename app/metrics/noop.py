"""Backend discarding every emission."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from app.metrics.base import _P, _R


class NoopBackend:
    """Backend discarding everything.

    Used when metrics are disabled and as the neutral element of
    :class:`app.metrics.composite.CompositeBackend`.
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
