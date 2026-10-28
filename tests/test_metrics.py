import functools
import sys
import types

import pytest

from app import config, metrics


class RecorderBackend:
    """Backend storing every emission in memory."""

    def __init__(self, name: str = "recorder"):
        self.name = name
        self.metrics: list[tuple[str, float]] = []
        self.events: list[tuple[str, dict[str, object]]] = []
        self.attributes: list[tuple[str, object]] = []

    def record_metric(self, name: str, value: float) -> None:
        self.metrics.append((name, value))

    def record_event(self, event_type: str, attributes) -> None:
        self.events.append((event_type, dict(attributes)))

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes.append((key, value))


class ExplodingBackend:
    """Backend failing on every emission."""

    def record_metric(self, name: str, value: float) -> None:
        raise RuntimeError("metric boom")

    def record_event(self, event_type: str, attributes) -> None:
        raise RuntimeError("event boom")

    def set_attribute(self, key: str, value: object) -> None:
        raise RuntimeError("attribute boom")


@pytest.fixture(autouse=True)
def restore_metrics_state():
    """Keep the process wide backend from leaking between tests."""
    original = metrics.get_backend()
    yield
    # Independent of monkeypatch teardown order: reinstall what was active
    # before the test, whatever config overrides it used.
    metrics.configure([original])


class TracingBackend:
    """Minimal backend implementing the optional tracing capability."""

    def __init__(self, name: str = "tracer") -> None:
        self.name = name
        self.wrapped: list[tuple[str | None, str | None, str]] = []

    def record_metric(self, name: str, value: float) -> None:
        """No-op: this backend only traces."""

    def record_event(self, event_type: str, attributes) -> None:
        """No-op: this backend only traces."""

    def set_attribute(self, key: str, value: object) -> None:
        """No-op: this backend only traces."""

    def background_task(self, func, *, name=None, group=None):
        self.wrapped.append((name, group, func.__qualname__))

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper


class BrokenTracer(TracingBackend):
    """Backend failing to install its wrapper."""

    def background_task(self, func, *, name=None, group=None):
        raise RuntimeError("cannot trace")


class LogRecorder:
    """Stand-in for ``app.metrics.LOG`` collecting emitted messages."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def e(self, message: str) -> None:
        self.errors.append(message)


@pytest.fixture
def log_recorder(monkeypatch) -> LogRecorder:
    """Capture the errors ``app.metrics`` reports.

    ``LOG`` is a dedicated logger whose handler writes straight to stdout and
    which does not propagate, so ``caplog`` cannot observe it: stub the logger
    itself instead.
    """
    recorder = LogRecorder()
    monkeypatch.setattr(metrics, "LOG", recorder)
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


def test_noop_backend_ignores_everything():
    backend = metrics.NoopBackend()
    backend.record_metric("Custom/x", 1)
    backend.record_event("X", {"a": 1})
    backend.set_attribute("a", 1)


def test_empty_backend_list_yields_noop_backend(monkeypatch):
    monkeypatch.setattr(config, "METRICS_BACKENDS", [])
    metrics.reset()

    assert isinstance(metrics.get_backend(), metrics.NoopBackend)


def test_single_backend_is_installed_as_is(monkeypatch):
    recorder = RecorderBackend()
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["recorder"])
    monkeypatch.setitem(metrics._BACKEND_FACTORIES, "recorder", lambda: recorder)
    metrics.reset()

    assert metrics.get_backend() is recorder


def test_several_backends_fan_out(monkeypatch):
    first = RecorderBackend("first")
    second = RecorderBackend("second")
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["first", "second"])
    monkeypatch.setitem(metrics._BACKEND_FACTORIES, "first", lambda: first)
    monkeypatch.setitem(metrics._BACKEND_FACTORIES, "second", lambda: second)
    metrics.reset()

    assert isinstance(metrics.get_backend(), metrics.CompositeBackend)

    metrics.record_metric("Custom/x", 3)
    metrics.record_event("X", {"a": 1})
    metrics.set_attribute("k", "v")

    for recorder in (first, second):
        assert recorder.metrics == [("Custom/x", 3)]
        assert recorder.events == [("X", {"a": 1})]
        assert recorder.attributes == [("k", "v")]


def test_duplicated_backend_names_emit_once(monkeypatch):
    recorder = RecorderBackend()
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["recorder", "recorder"])
    monkeypatch.setitem(metrics._BACKEND_FACTORIES, "recorder", lambda: recorder)
    metrics.reset()

    metrics.record_metric("Custom/x", 1)

    assert recorder.metrics == [("Custom/x", 1)]


def test_unknown_backend_name_raises_value_error():
    with pytest.raises(ValueError, match="Unknown metrics backend 'does-not-exist'"):
        metrics.backend_from_name("does-not-exist")


def test_unknown_backend_name_in_config_fails_fast(monkeypatch):
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["does-not-exist"])

    with pytest.raises(ValueError):
        metrics.reset()


def test_composite_backend_isolates_failing_backend(log_recorder):
    recorder = RecorderBackend()
    backend = metrics.CompositeBackend([ExplodingBackend(), recorder])

    # Neither exception escapes nor prevents the healthy backend from emitting.
    backend.record_metric("Custom/x", 2)
    backend.record_event("X", {"a": 1})
    backend.set_attribute("k", "v")

    assert recorder.metrics == [("Custom/x", 2)]
    assert recorder.events == [("X", {"a": 1})]
    assert recorder.attributes == [("k", "v")]
    assert len(log_recorder.errors) == 3
    assert "ExplodingBackend.record_metric failed" in log_recorder.errors[0]
    assert "event boom" in log_recorder.errors[1]
    assert "attribute boom" in log_recorder.errors[2]


def test_configure_overrides_the_active_backend():
    recorder = RecorderBackend()
    metrics.configure([recorder])

    assert metrics.get_backend() is recorder


def test_reset_restores_the_configured_backend(monkeypatch):
    monkeypatch.setattr(config, "METRICS_BACKENDS", [])
    metrics.configure([RecorderBackend()])
    metrics.reset()

    assert isinstance(metrics.get_backend(), metrics.NoopBackend)


def test_newrelic_backend_forwards_unchanged(fake_newrelic):
    backend = metrics.NewRelicBackend()
    backend.record_metric("Custom/postfix_incoming_queue", 12)
    backend.record_event("AliasCreated", {"automatic": "manual"})
    backend.set_attribute("alias_id", 42)

    assert fake_newrelic.metrics == [("Custom/postfix_incoming_queue", 12)]
    assert fake_newrelic.events == [("AliasCreated", {"automatic": "manual"})]
    assert fake_newrelic.attributes == [("alias_id", 42)]


def test_newrelic_backend_imports_the_sdk_lazily():
    backend = metrics.NewRelicBackend()

    assert backend._agent is None


def test_newrelic_backend_without_sdk_does_not_raise(monkeypatch, log_recorder):
    # ``None`` in sys.modules makes ``import newrelic`` raise ImportError.
    backend = metrics.NewRelicBackend()
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "newrelic", None)
        backend.record_metric("Custom/x", 1)
        backend.record_event("X", {})
        backend.set_attribute("k", "v")

    assert backend._import_failed is True
    # The failure is reported once, not on every subsequent emission.
    assert len(log_recorder.errors) == 1
    assert "newrelic is not importable" in log_recorder.errors[0]


def test_metrics_facade_uses_the_active_backend():
    recorder = RecorderBackend()
    metrics.configure([recorder])

    metrics.record_metric("Custom/x", 1.5)
    metrics.record_event("X", {"a": 1})
    metrics.set_attribute("k", "v")

    assert recorder.metrics == [("Custom/x", 1.5)]
    assert recorder.events == [("X", {"a": 1})]
    assert recorder.attributes == [("k", "v")]


def test_noop_backend_returns_the_function_unwrapped():
    backend = metrics.NoopBackend()

    def original(value: int) -> int:
        return value + 1

    assert backend.background_task(original) is original


def test_newrelic_backend_wraps_with_the_agent(fake_newrelic):
    backend = metrics.NewRelicBackend()

    def original(value: int) -> int:
        return value + 1

    wrapped = backend.background_task(original, name="Custom/x", group="Job")

    assert wrapped(1) == 2
    assert fake_newrelic.traces == [("Custom/x", "Job")]


def test_newrelic_backend_without_sdk_returns_the_function(monkeypatch):
    # ``None`` in sys.modules makes ``import newrelic`` raise ImportError.
    backend = metrics.NewRelicBackend()

    def original(value: int) -> int:
        return value + 1

    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "newrelic", None)
        assert backend.background_task(original) is original


def test_background_task_bare_form_traces_the_function():
    tracer = TracingBackend()
    metrics.configure([tracer])

    @metrics.background_task
    def decorate_me(value: int) -> int:
        return value * 2

    # Metadata survives so logs and tracebacks still name the decorated code.
    assert decorate_me(3) == 6
    assert decorate_me.__name__ == "decorate_me"
    name, group, qualname = tracer.wrapped[0]
    assert (name, group) == (None, None)
    assert qualname.endswith(".decorate_me")


def test_background_task_called_form_forwards_name_and_group():
    tracer = TracingBackend()
    metrics.configure([tracer])

    @metrics.background_task(name="Custom/named", group="Job")
    def decorate_me() -> str:
        return "traced"

    assert decorate_me() == "traced"
    assert tracer.wrapped[0][:2] == ("Custom/named", "Job")


def test_background_task_preserves_the_signature_of_a_method():
    tracer = TracingBackend()
    metrics.configure([tracer])

    class Handler:
        @metrics.background_task
        def handle(self, value: int) -> int:
            return value * 3

    assert Handler().handle(2) == 6


def test_background_task_without_tracing_backend_is_transparent():
    metrics.configure([RecorderBackend()])

    @metrics.background_task(name="Custom/x")
    def decorate_me(value: int) -> int:
        return value * 4

    assert decorate_me(2) == 8
    assert decorate_me.__name__ == "decorate_me"


def test_composite_backend_only_traces_on_capable_backends():
    tracer = TracingBackend()
    recorder = RecorderBackend()
    backend = metrics.CompositeBackend([recorder, tracer])

    def original() -> str:
        return "done"

    wrapped = backend.background_task(original, name="Custom/x")

    assert wrapped() == "done"
    assert tracer.wrapped[0][:2] == ("Custom/x", None)


def test_composite_backend_chains_several_tracers():
    first = TracingBackend("first")
    second = TracingBackend("second")
    backend = metrics.CompositeBackend([first, second])
    calls: list[str] = []

    def original() -> None:
        calls.append("original")

    wrapped = backend.background_task(original, name="Custom/x")
    wrapped()

    assert calls == ["original"]
    assert len(first.wrapped) == 1
    assert len(second.wrapped) == 1


def test_composite_backend_skips_a_failing_tracer(log_recorder):
    tracer = TracingBackend()
    backend = metrics.CompositeBackend([BrokenTracer(), tracer])

    def original() -> str:
        return "still works"

    wrapped = backend.background_task(original, name="Custom/x")

    assert wrapped() == "still works"
    # The healthy tracer still received the function.
    assert len(tracer.wrapped) == 1
    assert any("cannot trace" in error for error in log_recorder.errors)


def test_background_task_returns_the_function_when_wrapping_fails(log_recorder):
    metrics.configure([BrokenTracer()])

    def original() -> str:
        return "unwrapped"

    assert metrics._trace(original, name=None, group=None) is original
    assert any("could not be installed" in error for error in log_recorder.errors)
