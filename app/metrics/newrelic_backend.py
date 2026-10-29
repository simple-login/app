"""Backend forwarding the emissions to the New Relic agent."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.log import LOG
from app.metrics.base import _P, _R


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
