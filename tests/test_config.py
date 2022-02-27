import pytest

from app.config import sl_getenv


def test_sl_getenv(monkeypatch):
    monkeypatch.setenv("SL_KEY_1", '["domain_1"]')
    assert sl_getenv("SL_KEY_1") == ["domain_1"]

    assert sl_getenv("SL_KEY_2", default_factory=list) == []

    with pytest.raises(TypeError):
        sl_getenv("SL_KEY_3")
