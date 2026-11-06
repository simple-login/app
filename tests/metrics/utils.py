"""Stand-in backends shared by the metrics tests."""

import functools


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
    """Stand-in for the metrics modules' ``LOG`` collecting emitted messages."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def e(self, message: str) -> None:
        self.errors.append(message)

    def w(self, message: str) -> None:
        self.warnings.append(message)
