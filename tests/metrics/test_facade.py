import pytest

from app import config, metrics
from tests.metrics.utils import (
    BrokenTracer,
    RecorderBackend,
    TracingBackend,
)


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


def test_configure_overrides_the_active_backend():
    recorder = RecorderBackend()
    metrics.configure([recorder])

    assert metrics.get_backend() is recorder


def test_reset_restores_the_configured_backend(monkeypatch):
    monkeypatch.setattr(config, "METRICS_BACKENDS", [])
    metrics.configure([RecorderBackend()])
    metrics.reset()

    assert isinstance(metrics.get_backend(), metrics.NoopBackend)


def test_metrics_facade_uses_the_active_backend():
    recorder = RecorderBackend()
    metrics.configure([recorder])

    metrics.record_metric("Custom/x", 1.5)
    metrics.record_event("X", {"a": 1})
    metrics.set_attribute("k", "v")

    assert recorder.metrics == [("Custom/x", 1.5)]
    assert recorder.events == [("X", {"a": 1})]
    assert recorder.attributes == [("k", "v")]


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


def test_background_task_returns_the_function_when_wrapping_fails(log_recorder):
    metrics.configure([BrokenTracer()])

    def original() -> str:
        return "unwrapped"

    assert metrics._trace(original, name=None, group=None) is original
    assert any("could not be installed" in error for error in log_recorder.errors)


def test_prometheus_backend_is_registered_in_the_factory():
    backend = metrics.backend_from_name("prometheus")

    assert isinstance(backend, metrics.PrometheusBackend)
