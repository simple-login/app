from app.metrics.composite import CompositeBackend
from tests.metrics.utils import (
    BrokenTracer,
    ExplodingBackend,
    RecorderBackend,
    TracingBackend,
)


def test_composite_backend_isolates_failing_backend(log_recorder):
    recorder = RecorderBackend()
    backend = CompositeBackend([ExplodingBackend(), recorder])

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


def test_composite_backend_only_traces_on_capable_backends():
    tracer = TracingBackend()
    recorder = RecorderBackend()
    backend = CompositeBackend([recorder, tracer])

    def original() -> str:
        return "done"

    wrapped = backend.background_task(original, name="Custom/x")

    assert wrapped() == "done"
    assert tracer.wrapped[0][:2] == ("Custom/x", None)


def test_composite_backend_chains_several_tracers():
    first = TracingBackend("first")
    second = TracingBackend("second")
    backend = CompositeBackend([first, second])
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
    backend = CompositeBackend([BrokenTracer(), tracer])

    def original() -> str:
        return "still works"

    wrapped = backend.background_task(original, name="Custom/x")

    assert wrapped() == "still works"
    # The healthy tracer still received the function.
    assert len(tracer.wrapped) == 1
    assert any("cannot trace" in error for error in log_recorder.errors)
