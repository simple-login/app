from app.metrics.noop import NoopBackend


def test_noop_backend_ignores_everything():
    backend = NoopBackend()
    backend.record_metric("Custom/x", 1)
    backend.record_event("X", {"a": 1})
    backend.set_attribute("a", 1)


def test_noop_backend_returns_the_function_unwrapped():
    backend = NoopBackend()

    def original(value: int) -> int:
        return value + 1

    assert backend.background_task(original) is original
