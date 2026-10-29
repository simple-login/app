import sys

import pytest

from app.metrics.base import MetricsError, MetricTypeConflictError
from app.metrics.composite import CompositeBackend
from app.metrics.prometheus_backend import (
    MetricKind,
    PrometheusBackend,
    _sanitize_label_name,
    _sanitize_metric_name,
)
from tests.metrics.utils import RecorderBackend


def prometheus_registry():
    """Fresh registry per test, so no metric leaks across cases."""
    from prometheus_client import CollectorRegistry

    return CollectorRegistry()


def samples(
    registry, metric_name: str
) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    """Return ``{(sample name, sorted labels): value}`` for one family."""
    collected = {
        (sample.name, tuple(sorted(sample.labels.items()))): sample.value
        for metric in registry.collect()
        if metric.name == metric_name
        for sample in metric.samples
    }
    assert collected, f"{metric_name} is absent from the registry"
    return collected


def value_of(
    registry, metric_name: str, sample_suffix: str = "", **labels: str
) -> float:
    """Read one sample, addressed by its suffix and label values."""
    sample_key = (metric_name + sample_suffix, tuple(sorted(labels.items())))
    return samples(registry, metric_name)[sample_key]


def test_prometheus_sanitizes_metric_names():
    assert (
        _sanitize_metric_name("Custom/smtp_sending_time", "simplelogin")
        == "simplelogin_custom_smtp_sending_time"
    )
    # Nested New Relic names fold into a single flat name.
    assert (
        _sanitize_metric_name("Custom/nb_db_app_connection/main", "simplelogin")
        == "simplelogin_custom_nb_db_app_connection_main"
    )
    # A leading digit is illegal for a Prometheus name.
    assert _sanitize_metric_name("9lives", "sl") == "sl_9lives"
    assert _sanitize_metric_name("9lives", "") == "_9lives"
    # Nothing usable left: fall back instead of producing an empty name.
    assert _sanitize_metric_name("///", "") == "unnamed"


def test_prometheus_sanitizes_label_names():
    # Labels accept no colon and no leading digit, unlike metric names.
    assert _sanitize_label_name("alias-id") == "alias_id"
    assert _sanitize_label_name("1st") == "_1st"
    assert _sanitize_label_name("") == "label"


def test_prometheus_records_metric_and_event():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_metric("Custom/smtp_sending_time", 0.032)
    backend.record_metric("Custom/smtp_sending_time", 0.048)
    backend.record_event("AliasCreated", {"automatic": "manual"})

    assert value_of(registry, "sl_custom_smtp_sending_time", "_count") == 2
    # The histogram also gives the durations, which the counter view alone lost.
    assert round(value_of(registry, "sl_custom_smtp_sending_time", "_sum"), 6) == 0.08
    assert (
        value_of(
            registry,
            "sl_custom_event_aliascreated",
            "_total",
            automatic="manual",
        )
        == 1
    )


def test_prometheus_reuses_the_cached_instrument():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_metric("Custom/x", 1)
    backend.record_metric("Custom/x", 2)

    # One family only: the second emission reused the cached histogram.
    families = [m.name for m in registry.collect() if m.name == "sl_custom_x"]
    assert families == ["sl_custom_x"]


def test_prometheus_rejects_a_conflicting_type():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")
    backend.record_metric("Custom/x", 1)

    with pytest.raises(MetricTypeConflictError) as excinfo:
        backend._instrument_for("Custom/x", MetricKind.COUNTER, ())

    assert "was already registered as a histogram" in str(excinfo.value)
    assert isinstance(excinfo.value, MetricsError)


def test_prometheus_event_labels_come_from_the_attributes():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_event("PlanChange", {"plan": "premium", "type": "new"})
    backend.record_event("LoginEvent", {"action": "success", "source": "web"})

    # Each counter only carries the labels its own call site passes.
    assert samples(registry, "sl_custom_event_planchange") == {
        ("sl_custom_event_planchange_total", (("plan", "premium"), ("type", "new"))): 1
    }
    assert samples(registry, "sl_custom_event_loginevent") == {
        (
            "sl_custom_event_loginevent_total",
            (("action", "success"), ("source", "web")),
        ): 1
    }


def test_prometheus_event_omitting_a_label_exports_it_empty():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_event("PlanChange", {"plan": "premium", "type": "new"})
    backend.record_event("PlanChange", {"plan": "free"})

    name = "sl_custom_event_planchange"
    assert value_of(registry, name, "_total", plan="free", type="") == 1
    assert value_of(registry, name, "_total", plan="premium", type="new") == 1


def test_prometheus_event_drops_an_unknown_label_and_warns_once(log_recorder):
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_event("PlanChange", {"plan": "free"})
    backend.record_event("PlanChange", {"plan": "premium", "type": "new"})
    backend.record_event("PlanChange", {"plan": "premium", "type": "extension"})

    # The label names were fixed by the first emission: "type" cannot be added,
    # but the event is still counted rather than failing the caller.
    name = "sl_custom_event_planchange"
    assert value_of(registry, name, "_total", plan="premium") == 2
    assert len(log_recorder.warnings) == 1
    assert "'type'" in log_recorder.warnings[0]


def test_prometheus_ignores_attributes():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.set_attribute("alias_id", 42)

    # High cardinality identifiers must never become a series.
    assert list(registry.collect()) == []


def test_prometheus_backend_without_sdk_drops_silently(monkeypatch, log_recorder):
    monkeypatch.setitem(sys.modules, "prometheus_client", None)
    backend = PrometheusBackend()

    # A missing optional dependency must not break the business flow, and the
    # failure is reported once instead of on every emission.
    backend.record_metric("Custom/x", 1)
    backend.record_event("X", {"type": "y"})

    assert len(log_recorder.errors) == 1
    assert "not importable" in log_recorder.errors[0]


def test_prometheus_record_event_without_attributes():
    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_event("ClearAliasTrash", {})
    backend.record_event("ClearAliasTrash", {})

    assert value_of(registry, "sl_custom_event_clearaliastrash", "_total") == 2


def test_composite_keeps_working_when_prometheus_conflicts(log_recorder):
    registry = prometheus_registry()
    prometheus = PrometheusBackend(registry=registry, prefix="sl")
    recorder = RecorderBackend()
    backend = CompositeBackend([prometheus, recorder])

    # The event counter reuses the name ``record_metric`` gives the same string,
    # so the second call wants a counter where a histogram exists. Prometheus
    # cannot represent that, so the backend raises. Going through the composite
    # proves the failure reaches neither the caller nor the other backend, and
    # gets reported.
    backend.record_metric("Custom/event/E", 1)
    backend.record_event("E", {"type": "a"})

    assert recorder.metrics == [("Custom/event/E", 1)]
    assert recorder.events == [("E", {"type": "a"})]
    assert any(
        "PrometheusBackend.record_event failed" in error
        and "was already registered as a histogram" in error
        for error in log_recorder.errors
    )


def test_prometheus_backend_survives_a_reset(monkeypatch):
    """``metrics.reset()`` rebuilds the backend; the reused registry must cope.

    Registering the same name twice into one registry makes
    ``prometheus_client`` raise ``Duplicated timeseries``, so a rebuilt backend
    has to pick up the instruments already created.
    """
    registry = prometheus_registry()
    first = PrometheusBackend(registry=registry, prefix="sl")
    first.record_metric("Custom/x", 1)

    second = PrometheusBackend(registry=registry, prefix="sl")
    second.record_metric("Custom/x", 2)

    assert value_of(registry, "sl_custom_x", "_count") == 2


def test_prometheus_backends_sharing_a_registry_share_the_instruments():
    registry = prometheus_registry()
    first = PrometheusBackend(registry=registry, prefix="sl")
    second = PrometheusBackend(registry=registry, prefix="sl")

    first.record_metric("Custom/x", 1)
    second.record_metric("Custom/x", 3)

    # One histogram accumulating both emissions, not two fighting families.
    assert value_of(registry, "sl_custom_x", "_count") == 2
    assert round(value_of(registry, "sl_custom_x", "_sum"), 6) == 4.0


def test_prometheus_does_not_export_created_series():
    from prometheus_client import generate_latest

    registry = prometheus_registry()
    backend = PrometheusBackend(registry=registry, prefix="sl")

    backend.record_metric("Custom/smtp_sending_time", 0.032)
    backend.record_event("AliasCreated", {"automatic": "manual"})

    # The creation timestamp would show up as an extra "_created" gauge per series.
    assert "_created" not in generate_latest(registry).decode()
