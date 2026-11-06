import functools
import sys
import types

import pytest

from app import metrics
from app.metrics import composite, newrelic_backend, prometheus_backend
from tests.metrics.utils import LogRecorder


@pytest.fixture(autouse=True)
def restore_metrics_state():
    """Keep the process wide backend from leaking between tests."""
    original = metrics.get_backend()
    yield
    # Independent of monkeypatch teardown order: reinstall what was active
    # before the test, whatever config overrides it used.
    metrics.configure([original])


@pytest.fixture
def log_recorder(monkeypatch) -> LogRecorder:
    """Capture the errors the ``app.metrics`` modules report.

    ``LOG`` is a dedicated logger whose handler writes straight to stdout and
    which does not propagate, so ``caplog`` cannot observe it: stub the logger
    itself, in every module of the package that logs.
    """
    recorder = LogRecorder()
    for module in (metrics, composite, newrelic_backend, prometheus_backend):
        monkeypatch.setattr(module, "LOG", recorder)
    return recorder


class FakeNewRelicAgent:
    def __init__(self):
        self.metrics: list[tuple[str, float]] = []
        self.events: list[tuple[str, dict[str, object]]] = []
        self.attributes: list[tuple[str, object]] = []
        self.traces: list[tuple[str | None, str | None]] = []

    def record_custom_metric(self, name: str, value: float) -> None:
        self.metrics.append((name, value))

    def record_custom_event(self, event_type: str, attributes) -> None:
        self.events.append((event_type, dict(attributes)))

    def add_custom_attribute(self, key: str, value: object) -> None:
        self.attributes.append((key, value))

    def background_task(self, name=None, group=None):
        """Mirror ``newrelic.agent.background_task``'s partial factory."""
        self.traces.append((name, group))

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

            return wrapper

        return decorator


@pytest.fixture
def fake_newrelic(monkeypatch) -> FakeNewRelicAgent:
    """Inject a stand-in ``newrelic`` package into ``sys.modules``."""
    agent = FakeNewRelicAgent()
    module = types.ModuleType("newrelic")
    module.agent = agent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "newrelic", module)
    return agent
