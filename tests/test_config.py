import importlib

import pytest

from app import config
from app.config import sl_getenv


def test_session_pickle_fallback_enabled_by_default(monkeypatch):
    monkeypatch.delenv("SESSION_PICKLE_FALLBACK", raising=False)
    assert config.SESSION_PICKLE_FALLBACK is True


def test_session_pickle_fallback_can_be_disabled(monkeypatch):
    # config is imported once, so reload it with the env var set
    monkeypatch.setenv("SESSION_PICKLE_FALLBACK", "false")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.SESSION_PICKLE_FALLBACK is False
    finally:
        monkeypatch.delenv("SESSION_PICKLE_FALLBACK", raising=False)
        importlib.reload(config)


def test_sl_getenv(monkeypatch):
    monkeypatch.setenv("SL_KEY_1", '["domain_1"]')
    assert sl_getenv("SL_KEY_1") == ["domain_1"]

    assert sl_getenv("SL_KEY_2", default_factory=list) == []

    with pytest.raises(TypeError):
        sl_getenv("SL_KEY_3")
