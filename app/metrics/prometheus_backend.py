"""Backend recording the emissions into ``prometheus_client`` instruments.

Only the recording side lives here; the exposition (scrape listeners and the
``/metrics`` view) lives in :mod:`app.prometheus_export`.
"""

from __future__ import annotations

import re
import threading
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import TYPE_CHECKING

from app import config
from app.log import LOG
from app.metrics.base import MetricsError, MetricTypeConflictError

if TYPE_CHECKING:
    from prometheus_client import CollectorRegistry
    from prometheus_client.metrics import MetricWrapperBase


class MetricKind(str, Enum):
    """Prometheus instrument kind backing a metric name.

    ``COUNTER`` backs :meth:`PrometheusBackend.record_event`, ``HISTOGRAM``
    backs :meth:`PrometheusBackend.record_metric`. ``GAUGE`` is reserved: no
    call site needs a set-to-a-value semantic yet, and the facade has no way to
    express "last value wins". It is kept so that :class:`MetricTypeConflictError`
    can report a clash involving a gauge introduced later, instead of having to
    widen the enum then.
    """

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class _RegisteredMetric:
    """Definition cached for one metric name."""

    kind: MetricKind
    labels: tuple[str, ...]
    instrument: MetricWrapperBase


class _InstrumentCache:
    """Thread safe ``(registry, name) -> instrument`` table shared process wide.

    A :class:`PrometheusBackend` instance could own this cache, but
    :func:`app.metrics.reset` and :func:`app.metrics.configure` rebuild the
    backend from scratch, and a second registration of the same name into the
    same registry makes ``prometheus_client`` raise ``Duplicated timeseries in
    CollectorRegistry``.
    Sharing the cache by registry keeps a rebuilt backend usable and makes two
    backends pointing at one registry agree on a single instrument.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self._by_registry: weakref.WeakKeyDictionary[
            CollectorRegistry, dict[str, _RegisteredMetric]
        ] = weakref.WeakKeyDictionary()

    def table(
        self, registry: CollectorRegistry, *, create: bool = False
    ) -> dict[str, _RegisteredMetric]:
        """Return the metric table of ``registry``.

        Must be called with :attr:`lock` held. An empty table is created and
        tracked when ``create`` is set and the registry is unknown; otherwise
        the returned mapping is detached and must not be mutated.
        """
        table = self._by_registry.get(registry)
        if table is None and create:
            table = {}
            self._by_registry[registry] = table

        return table if table is not None else {}


_INSTRUMENTS = _InstrumentCache()


_INVALID_METRIC_CHARS = re.compile(r"[^a-zA-Z0-9_:]")
_INVALID_LABEL_CHARS = re.compile(r"[^a-zA-Z0-9_]")
_VALID_METRIC_START = re.compile(r"[a-zA-Z_:]")
_VALID_LABEL_START = re.compile(r"[a-zA-Z_]")


def _sanitize_metric_name(name: str, prefix: str) -> str:
    """Turn ``name`` into a valid Prometheus metric name.

    Prometheus only accepts ``[a-zA-Z_:][a-zA-Z0-9_:]*``. Existing call sites
    emit namespaced New Relic style names such as ``Custom/smtp_sending_time``
    or ``Custom/nb_db_app_connection/main`` whose separators are not legal, so
    they are folded into underscores, lower cased to follow the Prometheus
    naming conventions, and the configured prefix is prepended::

        >>> _sanitize_metric_name("Custom/smtp_sending_time", "simplelogin")
        'simplelogin_custom_smtp_sending_time'

    Returns:
        A name matching the Prometheus grammar, never empty.
    """
    sanitized = _INVALID_METRIC_CHARS.sub("_", name).strip("_").lower()
    if not sanitized:
        sanitized = "unnamed"

    prefixed = f"{prefix}_{sanitized}" if prefix else sanitized
    if not _VALID_METRIC_START.match(prefixed):
        # The prefix cannot start with a digit, so this covers a bare name
        # starting with one.
        prefixed = f"_{prefixed}"

    return prefixed


def _sanitize_label_name(name: str) -> str:
    """Turn ``name`` into a valid Prometheus label name.

    Label names follow ``[a-zA-Z_][a-zA-Z0-9_]*``: no colon and no leading
    digit, unlike metric names.

        >>> _sanitize_label_name("alias-id")
        'alias_id'
    """
    sanitized = _INVALID_LABEL_CHARS.sub("_", name).strip("_")
    if not sanitized:
        sanitized = "label"
    if not _VALID_LABEL_START.match(sanitized):
        sanitized = f"_{sanitized}"

    return sanitized


class PrometheusBackend:
    """Backend exposing the emissions through ``prometheus_client``.

    Metrics are created lazily, on the first emission for a given name, because
    the set of emitted names depends on the workload and building thousands of
    instruments up front would cost both memory and startup time. Instruments
    are cached by name afterwards: a Prometheus metric is bound to one kind and
    one label set for the whole life of the process, so a later emission reusing
    the name differently raises :class:`MetricTypeConflictError` instead of
    silently producing inconsistent series.

    ``record_metric`` observes every value on a histogram, ``record_event``
    counts events labelled with their attributes and ``set_attribute`` is a
    no-op since Prometheus has no attribute concept.

    ``prometheus_client`` is imported inside the methods so this module, and
    everything importing it, keeps working where the SDK is absent.

    Example:
        >>> from prometheus_client import CollectorRegistry
        >>> backend = PrometheusBackend(registry=CollectorRegistry())
        >>> backend.record_metric("Custom/number_incoming_email", 1)
    """

    def __init__(
        self,
        registry: CollectorRegistry | None = None,
        *,
        prefix: str | None = None,
    ) -> None:
        """Bind the backend to ``registry`` and metric name ``prefix``.

        Args:
            registry: collectors to register into. Left unset the process wide
                default registry is used; passing an isolated one keeps tests
                independent.
            prefix: namespace prepended to every metric name, defaulting to
                ``config.PROMETHEUS_METRIC_PREFIX``.
        """
        self._registry = registry
        self._prefix = config.PROMETHEUS_METRIC_PREFIX if prefix is None else prefix
        self._client: ModuleType | None = None
        self._import_failed = False
        # (metric, label) pairs already reported as dropped, to warn only once.
        self._dropped_labels: set[tuple[str, str]] = set()

    @property
    def registry(self) -> CollectorRegistry | None:
        """The injected registry, or ``None`` for the process wide default."""
        return self._registry

    def _get_client(self) -> ModuleType | None:
        """Import ``prometheus_client`` once, reporting the failure once."""
        if self._client is None and not self._import_failed:
            try:
                import prometheus_client
            except ImportError as e:
                self._import_failed = True
                LOG.e(f"prometheus_client is not importable, metrics are dropped: {e}")
                return None
            # By default every counter and histogram also exports a "<name>_created"
            # series holding its creation timestamp, typed as a gauge in the text
            # format. Prometheus does not need it and it doubles the series count.
            prometheus_client.disable_created_metrics()
            self._client = prometheus_client

        return self._client

    def _resolve_registry(self, client: ModuleType) -> CollectorRegistry:
        """Return the registry the instruments must register into.

        The injected registry wins, then the process wide default one. In
        multiprocess mode the default registry stays the right place to
        register: it is what writes the mmapped files the workers share. Only
        the *exposition* differs there, and that is handled by
        :func:`app.prometheus_export.metrics_payload` through
        ``MultiProcessCollector``.
        """
        if self._registry is not None:
            return self._registry

        return client.REGISTRY

    def _instrument_for(
        self, name: str, kind: MetricKind, labels: tuple[str, ...]
    ) -> _RegisteredMetric:
        """Create the instrument for ``name``, or return the cached one.

        ``labels`` only matters on creation: a cached instrument keeps the label
        names it was created with, which the caller reconciles with its own.

        Raises:
            MetricTypeConflictError: if ``name`` was registered earlier with
                another kind.
            MetricsError: if ``prometheus_client`` is unavailable or refuses the
                name (for example because another collector owns it).
        """
        client = self._get_client()
        if client is None:
            raise MetricsError("prometheus_client is not importable")

        sanitized = _sanitize_metric_name(name, self._prefix)
        caller_label_names = tuple(_sanitize_label_name(label) for label in labels)
        registry = self._resolve_registry(client)

        with _INSTRUMENTS.lock:
            metrics = _INSTRUMENTS.table(registry, create=True)
            cached = metrics.get(sanitized)
            if cached is not None:
                if cached.kind is not kind:
                    raise MetricTypeConflictError(
                        sanitized,
                        f"was already registered as a {cached.kind}, "
                        f"cannot also be a {kind}",
                    )
                return cached

            documentations = {
                MetricKind.COUNTER: f"Total number of {sanitized} events",
                MetricKind.GAUGE: f"Current value of {sanitized}",
                MetricKind.HISTOGRAM: f"Distribution of {sanitized}",
            }
            documentation = documentations[kind]
            kwargs: dict[str, object] = {
                "documentation": documentation,
                "registry": registry,
            }
            if caller_label_names:
                kwargs["labelnames"] = caller_label_names

            builders: dict[MetricKind, Callable[..., MetricWrapperBase]] = {
                MetricKind.COUNTER: client.Counter,
                MetricKind.GAUGE: client.Gauge,
                MetricKind.HISTOGRAM: client.Histogram,
            }
            try:
                instrument = builders[kind](sanitized, **kwargs)
            except ValueError as e:
                raise MetricsError(
                    f"prometheus_client rejected the metric '{sanitized}': {e}"
                ) from e

            registered = _RegisteredMetric(
                kind=kind, labels=caller_label_names, instrument=instrument
            )
            metrics[sanitized] = registered
            return registered

    def record_metric(self, name: str, value: float) -> None:
        """Observe ``value`` for ``name``.

        Every recorded value goes to a histogram, whatever its magnitude: the
        instrument kind only depends on the name, so a call site emitting ``1``
        for one occurrence and ``3`` for three of them never hits a kind clash.
        A histogram carries everything a dashboard needs: ``_count`` gives the
        number of occurrences (the counter view), ``_sum``/
        ``_count`` the average and the buckets quantiles, which also fits the
        durations and queue lengths the call sites record.

        Silently drops the value when ``prometheus_client`` is unavailable: the
        import failure is logged once by :meth:`_get_client`, and repeating it
        on every emission would bury the rest of the log.
        """
        if self._get_client() is None:
            return

        self._instrument_for(name, MetricKind.HISTOGRAM, ()).instrument.observe(
            float(value)
        )

    def record_event(self, event_type: str, attributes: Mapping[str, object]) -> None:
        """Count the event, labelled with its attributes.

        Every attribute becomes a label, so the call site decides the label set
        of its counter. Two consequences for the call sites:

        - every distinct label *value* is a separate time series, so an
          attribute must hold a short, enumerable value, never an identifier;
        - an event type must always be emitted with the same keys. Prometheus
          fixes the label names of a counter when it is created, on the first
          emission. A later emission omitting a key exports it as an empty
          string; a key the counter does not have is dropped and reported once.

        Values are stringified because Prometheus labels are always strings; the
        call sites pass scalars and enum members.

        >>> from prometheus_client import CollectorRegistry
        >>> backend = PrometheusBackend(registry=CollectorRegistry())
        >>> backend.record_event("PlanChange", {"plan": "premium", "type": "new"})
        """
        if self._get_client() is None:
            return

        values = {
            _sanitize_label_name(key): str(value) for key, value in attributes.items()
        }
        registered = self._instrument_for(
            f"Custom/event/{event_type}", MetricKind.COUNTER, tuple(sorted(values))
        )

        for label in values.keys() - set(registered.labels):
            self._report_dropped_label(event_type, label, registered.labels)

        if not registered.labels:
            registered.instrument.inc()
            return

        registered.instrument.labels(
            **{label: values.get(label, "") for label in registered.labels}
        ).inc()

    def _report_dropped_label(
        self, event_type: str, label: str, known: tuple[str, ...]
    ) -> None:
        """Warn, once per event type and label, about a label that was dropped."""
        if (event_type, label) in self._dropped_labels:
            return

        self._dropped_labels.add((event_type, label))
        LOG.w(
            f"Event {event_type} emitted with the label {label!r} its counter was "
            f"not created with {known}: the label is dropped. Emit {event_type} "
            "with the same attributes everywhere."
        )

    def set_attribute(self, key: str, value: object) -> None:
        """Ignore the attribute.

        Attributes decorate a unit of work in New Relic or Sentry but Prometheus
        has no equivalent: exporting them would mean one label per attribute
        value, and those values are often identifiers such as user or alias ids.
        That is unbounded label cardinality, which is precisely what takes a
        Prometheus server down, so the attribute is deliberately dropped.
        """
