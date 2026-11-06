"""Tests for the Prometheus hooks of the gunicorn configuration.

``gunicorn.conf.py`` sits at the repository root and is not importable as a
package module, so it is loaded by path the same way gunicorn does.
"""

import importlib.util
import os
import pathlib

import pytest

from app import config

CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "gunicorn.conf.py"


@pytest.fixture
def gunicorn_conf():
    """The configuration module, reloaded so monkeypatched values apply."""
    spec = importlib.util.spec_from_file_location("gunicorn_conf", CONFIG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeServer:
    """Stand-in for ``gunicorn.app.base.Application``: only ``log`` is used."""

    def __init__(self) -> None:
        self.infos: list[str] = []

        server = self

        class Log:
            @staticmethod
            def info(message, *args) -> None:
                server.infos.append(message % args if args else message)

        self.log = Log()


class FakeWorker:
    def __init__(self, pid: int) -> None:
        self.pid = pid


@pytest.fixture
def multiproc(tmp_path, monkeypatch):
    """Enable multiprocess mode with the Prometheus backend selected."""
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["prometheus"])
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    return tmp_path


def test_on_starting_clears_the_directory(gunicorn_conf, multiproc):
    stale = multiproc / "counter_1.db"
    stale.write_bytes(b"from a previous generation")

    gunicorn_conf.on_starting(FakeServer())

    # Inherited counters would inflate every total for the whole deployment.
    assert not stale.exists()


def test_hooks_are_inert_without_the_prometheus_backend(
    gunicorn_conf, multiproc, monkeypatch
):
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["newrelic"])
    stale = multiproc / "counter_1.db"
    stale.write_bytes(b"keep")

    gunicorn_conf.on_starting(FakeServer())

    assert stale.exists()


def test_child_exit_releases_the_worker_files(gunicorn_conf, multiproc, monkeypatch):
    released: list[int] = []
    monkeypatch.setattr(gunicorn_conf, "mark_worker_dead", released.append)
    server = FakeServer()

    gunicorn_conf.child_exit(server, FakeWorker(4321))

    assert released == [4321]
    assert any("4321" in info for info in server.infos)


def test_a_temporary_directory_is_used_when_none_is_configured(monkeypatch):
    monkeypatch.setattr(config, "METRICS_BACKENDS", ["prometheus"])
    monkeypatch.setattr(config, "PROMETHEUS_MULTIPROC_DIR", None)
    # setenv first so that the undo removes what the module exports.
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", "")
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR")

    spec = importlib.util.spec_from_file_location("gunicorn_conf", CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Without it, every worker keeps a private registry and fights the others
    # for the listener port.
    directory = config.PROMETHEUS_MULTIPROC_DIR
    assert directory and pathlib.Path(directory).is_dir()
    assert os.environ["PROMETHEUS_MULTIPROC_DIR"] == directory

    module.on_exit(FakeServer())

    assert not pathlib.Path(directory).exists()


def test_a_configured_directory_is_kept_on_exit(gunicorn_conf, multiproc):
    gunicorn_conf.on_exit(FakeServer())

    assert multiproc.is_dir()
