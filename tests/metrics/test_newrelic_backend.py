import sys

from app.metrics.newrelic_backend import NewRelicBackend


def test_newrelic_backend_forwards_unchanged(fake_newrelic):
    backend = NewRelicBackend()
    backend.record_metric("Custom/postfix_incoming_queue", 12)
    backend.record_event("AliasCreated", {"automatic": "manual"})
    backend.set_attribute("alias_id", 42)

    assert fake_newrelic.metrics == [("Custom/postfix_incoming_queue", 12)]
    assert fake_newrelic.events == [("AliasCreated", {"automatic": "manual"})]
    assert fake_newrelic.attributes == [("alias_id", 42)]


def test_newrelic_backend_imports_the_sdk_lazily():
    backend = NewRelicBackend()

    assert backend._agent is None


def test_newrelic_backend_without_sdk_does_not_raise(monkeypatch, log_recorder):
    # ``None`` in sys.modules makes ``import newrelic`` raise ImportError.
    backend = NewRelicBackend()
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "newrelic", None)
        backend.record_metric("Custom/x", 1)
        backend.record_event("X", {})
        backend.set_attribute("k", "v")

    assert backend._import_failed is True
    # The failure is reported once, not on every subsequent emission.
    assert len(log_recorder.errors) == 1
    assert "newrelic is not importable" in log_recorder.errors[0]


def test_newrelic_backend_wraps_with_the_agent(fake_newrelic):
    backend = NewRelicBackend()

    def original(value: int) -> int:
        return value + 1

    wrapped = backend.background_task(original, name="Custom/x", group="Job")

    assert wrapped(1) == 2
    assert fake_newrelic.traces == [("Custom/x", "Job")]


def test_newrelic_backend_without_sdk_returns_the_function(monkeypatch):
    # ``None`` in sys.modules makes ``import newrelic`` raise ImportError.
    backend = NewRelicBackend()

    def original(value: int) -> int:
        return value + 1

    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "newrelic", None)
        assert backend.background_task(original) is original
