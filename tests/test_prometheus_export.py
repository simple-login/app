"""Tests for the Prometheus exposition: bearer auth, payload and multiprocess."""

import hmac
import os

import pytest

from app import config, prometheus_export


@pytest.fixture
def log_recorder(monkeypatch):
    """Capture the errors the metrics modules report.

    ``LOG`` is a dedicated logger writing straight to stdout without
    propagating, so ``caplog`` cannot observe it: stub the logger instead.
    """

    class Recorder:
        def __init__(self) -> None:
            self.errors: list[str] = []
            self.infos: list[str] = []
            self.warnings: list[str] = []

        def e(self, message: str) -> None:
            self.errors.append(message)

        def i(self, message: str) -> None:
            self.infos.append(message)

        def w(self, message: str) -> None:
            self.warnings.append(message)

    recorder = Recorder()
    monkeypatch.setattr(prometheus_export, "LOG", recorder)
    return recorder


@pytest.fixture
def metrics_app(endpoint_enabled):
    """A bare Flask app carrying only the /metrics blueprint.

    Building a dedicated app keeps the assertions independent of the routes,
    sessions and middleware of the real application.
    """
    flask = pytest.importorskip("flask")

    app = flask.Flask(__name__)
    blueprint = prometheus_export.create_metrics_blueprint()
    assert blueprint is not None
    app.register_blueprint(blueprint)
    return app


@pytest.fixture
def endpoint_enabled(monkeypatch):
    """Configure the endpoint with a known token."""
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")


def test_auth_accepts_the_configured_token(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")

    assert prometheus_export.is_auth_valid("Bearer s3cret-token") is True


def test_auth_rejects_a_missing_header(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")

    assert prometheus_export.is_auth_valid(None) is False
    assert prometheus_export.is_auth_valid("") is False


def test_auth_rejects_a_wrong_token(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")

    assert prometheus_export.is_auth_valid("Bearer guess") is False
    # A prefix of the real token must not pass either.
    assert prometheus_export.is_auth_valid("Bearer s3cret") is False


def test_auth_rejects_another_scheme(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")

    # Basic auth must not be interpreted as a bearer token.
    assert prometheus_export.is_auth_valid("s3cret-token") is False
    assert prometheus_export.is_auth_valid("Basic s3cret-token") is False


def test_auth_refuses_everything_without_a_configured_token(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", None)

    # Fail closed: no token configured means nobody is authorised.
    assert prometheus_export.is_auth_valid("Bearer ") is False
    assert prometheus_export.is_auth_valid("Bearer anything") is False


def test_auth_compares_in_constant_time(monkeypatch):
    calls: list[tuple[str, str]] = []
    real_compare = hmac.compare_digest

    def spy(first: str, second: str) -> bool:
        calls.append((first, second))
        return real_compare(first, second)

    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")
    monkeypatch.setattr(prometheus_export.hmac, "compare_digest", spy)

    assert prometheus_export.is_auth_valid("Bearer s3cret-token") is True
    assert calls == [("s3cret-token", "s3cret-token")]


def test_blueprint_is_absent_without_a_token(monkeypatch, log_recorder):
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", None)

    # Misconfiguration disables the route rather than opening it.
    assert prometheus_export.create_metrics_blueprint() is None
    assert any("stays disabled" in error for error in log_recorder.errors)


def test_endpoint_rejects_a_missing_token(metrics_app, endpoint_enabled):
    response = metrics_app.test_client().get("/metrics")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == 'Bearer realm="metrics"'


def test_endpoint_rejects_a_wrong_token(metrics_app, endpoint_enabled):
    response = metrics_app.test_client().get(
        "/metrics", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 401


def test_endpoint_serves_the_exposition_with_the_right_token(
    metrics_app, endpoint_enabled, monkeypatch
):
    # The payload normally comes from the process wide REGISTRY, shared by the
    # whole session: creating a real counter there makes a rerun fail with
    # "Duplicated timeseries". Patch the rendering rather than pollute it.
    monkeypatch.setattr(
        prometheus_export,
        "metrics_payload",
        lambda: (b"some_counter_total 1.0\n", "text/plain; version=0.0.4"),
    )

    response = metrics_app.test_client().get(
        "/metrics", headers={"Authorization": "Bearer s3cret-token"}
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    assert "some_counter_total 1.0" in response.get_data(as_text=True)


def test_prometheus_enabled_reads_the_backend_list(monkeypatch):
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["newrelic"])
    assert prometheus_export.prometheus_enabled() is False

    monkeypatch.setattr(config, "METRICS_BACKENDS", ["newrelic", "prometheus"])
    assert prometheus_export.prometheus_enabled() is True


def test_prepare_multiproc_dir_clears_stale_files(tmp_path):
    stale = tmp_path / "counter_1.db"
    stale.write_bytes(b"stale")
    kept = tmp_path / "notes.txt"
    kept.write_text("keep me")

    result = prometheus_export.prepare_multiproc_dir(str(tmp_path))

    assert result == str(tmp_path)
    # Counters from a previous generation would double every total.
    assert not stale.exists()
    # Anything unrelated is left alone.
    assert kept.exists()


def test_prepare_multiproc_dir_creates_a_missing_directory(tmp_path):
    target = tmp_path / "nested" / "metrics"

    assert prometheus_export.prepare_multiproc_dir(str(target)) == str(target)
    assert os.path.isdir(target)


def test_prepare_multiproc_dir_is_a_noop_without_configuration(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", None)

    assert prometheus_export.prepare_multiproc_dir() is None


def test_mark_worker_dead_drops_the_live_gauge_files(tmp_path, monkeypatch):
    pytest.importorskip("prometheus_client.multiprocess")
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    # Live gauges must go: a recycled worker would otherwise keep reporting.
    live_gauge = tmp_path / "gauge_liveall_12345.db"
    live_gauge.write_bytes(b"orphan")
    # Counters are cumulative and must survive a worker recycle, otherwise every
    # restart would reset the totals to zero.
    counter = tmp_path / "counter_12345.db"
    counter.write_bytes(b"cumulative")

    prometheus_export.mark_worker_dead(12345)

    assert not live_gauge.exists()
    assert counter.exists()


def test_mark_worker_dead_is_a_noop_without_multiprocess(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", None)
    untouched = tmp_path / "gauge_liveall_1.db"
    untouched.write_bytes(b"stay")

    prometheus_export.mark_worker_dead(1)

    assert untouched.exists()


def test_setup_prometheus_routes_metrics_on_the_given_app(monkeypatch):
    """The app factory has no pushed context: the blueprint goes on ``app``."""
    flask = pytest.importorskip("flask")
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["prometheus"])
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", None)

    app = flask.Flask(__name__)
    prometheus_export.setup_prometheus(app)

    # Routed, not merely registered: an app context is needed to introspect it,
    # and the factory itself has none, which is exactly what used to break.
    assert "/metrics" in {rule.rule for rule in app.url_map.iter_rules()}


def test_setup_prometheus_leaves_the_multiproc_files_alone(tmp_path, monkeypatch):
    """Cleaning is the master's job: a worker must not wipe its siblings."""
    flask = pytest.importorskip("flask")
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["prometheus"])
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    sibling = tmp_path / "counter_4242.db"
    sibling.write_bytes(b"still being written by another worker")

    prometheus_export.setup_prometheus(flask.Flask(__name__))

    assert sibling.exists()


def test_ensure_multiproc_env_reports_an_unexported_directory(
    tmp_path, monkeypatch, log_recorder
):
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    # prometheus_client reads the variable from os.environ when it is imported,
    # so a late config value would silently give every worker a private
    # registry that looks healthy while reporting a fraction of the traffic.
    assert prometheus_export.ensure_multiproc_env() is False
    assert any("was not exported" in error for error in log_recorder.errors)


def test_ensure_multiproc_env_accepts_a_properly_exported_directory(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))

    assert prometheus_export.ensure_multiproc_env() is True


def test_ensure_multiproc_env_is_a_noop_without_multiprocess(monkeypatch):
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", None)

    assert prometheus_export.ensure_multiproc_env() is True


def test_populate_multiproc_dir_exports_the_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)

    prometheus_export.populate_multiproc_dir(str(tmp_path))

    # prometheus_client reads it from os.environ when it is imported, so the
    # exported value is the only thing that counts.
    assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == str(tmp_path)


def test_setup_prometheus_does_nothing_for_another_backend(monkeypatch):
    flask = pytest.importorskip("flask")
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["newrelic"])
    monkeypatch.setattr(config, "PROMETHEUS_METRICS_TOKEN", "s3cret-token")

    app = flask.Flask(__name__)
    prometheus_export.setup_prometheus(app)

    assert "/metrics" not in {rule.rule for rule in app.url_map.iter_rules()}


def test_endpoint_aggregates_the_worker_files(tmp_path, monkeypatch):
    """Under gunicorn any worker may answer the scrape: it must report them all."""
    pytest.importorskip("prometheus_client.multiprocess")
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    aggregated: list[str] = []
    real_registry = prometheus_export._multiproc_registry

    def spy(directory: str):
        aggregated.append(directory)
        return real_registry(directory)

    monkeypatch.setattr(prometheus_export, "_multiproc_registry", spy)

    _, content_type = prometheus_export.metrics_payload()

    assert content_type.startswith("text/plain")
    assert aggregated == [str(tmp_path)]
