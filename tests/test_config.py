import importlib
from typing import Optional

import pytest

from app import config
from app.config import sl_getenv


def test_session_pickle_fallback_enabled_by_default(monkeypatch):
    monkeypatch.delenv("SESSION_PICKLE_FALLBACK", raising=False)
    assert config.SESSION_PICKLE_FALLBACK is True


def _capture_config_values(monkeypatch, **env) -> dict:
    """Reload config with the given session env vars set and return the
    resulting session-related values. Always leaves the shared config module
    and the environment as they were: never let an exception escape from the
    reload, a failed import leaves the module half-initialized and the cleanup
    below cannot undo that from inside a pytest.raises context."""
    monkeypatch.setenv(
        "SESSION_PICKLE_FALLBACK", env.get("SESSION_PICKLE_FALLBACK", "true")
    )
    if "SESSION_SERIALIZATION" in env:
        monkeypatch.setenv("SESSION_SERIALIZATION", env["SESSION_SERIALIZATION"])
    else:
        monkeypatch.delenv("SESSION_SERIALIZATION", raising=False)
    try:
        importlib.reload(importlib.import_module("app.config"))
        return {
            "SESSION_PICKLE_FALLBACK": config.SESSION_PICKLE_FALLBACK,
            "SESSION_SERIALIZATION": config.SESSION_SERIALIZATION,
        }
    finally:
        monkeypatch.delenv("SESSION_PICKLE_FALLBACK", raising=False)
        monkeypatch.delenv("SESSION_SERIALIZATION", raising=False)
        # Env is back to the test defaults here, so this reload gives the
        # shared module its clean state again.
        importlib.reload(importlib.import_module("app.config"))


def _config_import_error(monkeypatch, **env) -> Optional[Exception]:
    """Reload config with the given env vars; return the exception raised at
    import, or None. Restores the environment and a clean config either way."""
    monkeypatch.setenv(
        "SESSION_PICKLE_FALLBACK", env.get("SESSION_PICKLE_FALLBACK", "true")
    )
    monkeypatch.setenv("SESSION_SERIALIZATION", env["SESSION_SERIALIZATION"])
    try:
        importlib.reload(importlib.import_module("app.config"))
        return None
    except Exception as exc:
        return exc
    finally:
        monkeypatch.delenv("SESSION_PICKLE_FALLBACK", raising=False)
        monkeypatch.delenv("SESSION_SERIALIZATION", raising=False)
        importlib.reload(importlib.import_module("app.config"))


def test_session_pickle_fallback_can_be_disabled(monkeypatch):
    # config is imported once, so reload it with the env var set. Writing
    # pickle while refusing to read it is rejected, so json is required here.
    values = _capture_config_values(
        monkeypatch,
        SESSION_PICKLE_FALLBACK="false",
        SESSION_SERIALIZATION="json",
    )
    assert values["SESSION_PICKLE_FALLBACK"] is False


def test_session_serialization_defaults_to_pickle(monkeypatch):
    values = _capture_config_values(monkeypatch)
    assert values["SESSION_SERIALIZATION"] == "pickle"


@pytest.mark.parametrize("value", ["json", "JSON", "Json"])
def test_session_serialization_accepts_json_case_insensitively(monkeypatch, value: str):
    values = _capture_config_values(monkeypatch, SESSION_SERIALIZATION=value)
    assert values["SESSION_SERIALIZATION"] == "json"


@pytest.mark.parametrize("value", ["PICKLE", "Pickle"])
def test_session_serialization_accepts_pickle_case_insensitively(
    monkeypatch, value: str
):
    values = _capture_config_values(monkeypatch, SESSION_SERIALIZATION=value)
    assert values["SESSION_SERIALIZATION"] == "pickle"


def test_session_serialization_rejects_invalid_value(monkeypatch):
    exc = _config_import_error(monkeypatch, SESSION_SERIALIZATION="msgpack")
    assert isinstance(exc, ValueError)


def test_session_serialization_pickle_requires_pickle_fallback(monkeypatch):
    # A worker that writes pickle but refuses to read it would log every user
    # out on every request.
    exc = _config_import_error(
        monkeypatch,
        SESSION_PICKLE_FALLBACK="false",
        SESSION_SERIALIZATION="pickle",
    )
    assert isinstance(exc, ValueError)


def test_sl_getenv(monkeypatch):
    monkeypatch.setenv("SL_KEY_1", '["domain_1"]')
    assert sl_getenv("SL_KEY_1") == ["domain_1"]

    assert sl_getenv("SL_KEY_2", default_factory=list) == []

    with pytest.raises(TypeError):
        sl_getenv("SL_KEY_3")
