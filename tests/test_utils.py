from app.utils import random_string, random_words
import pytest


def test_random_words():
    s = random_words()
    assert len(s) > 0


def test_random_string():
    s = random_string()
    assert len(s) > 0


def test_parse_environment():
    from app.config import parse_environment

    array = parse_environment('["word_1", "word_2"]')
    assert array == ["word_1", "word_2"]
    env_tuple = parse_environment('("word_1", "word_2")')
    assert env_tuple == ("word_1", "word_2")
    env_list_tuple = parse_environment('[(10, "domain_1")]')
    assert [(10, "domain_1")] == env_list_tuple
    failed_python_object = parse_environment("a")
    assert failed_python_object is None


def test_sl_get_env(monkeypatch):
    from app.config import sl_get_env

    monkeypatch.setenv("SL_KEY_1", '["domain_1"]')
    key_1 = sl_get_env("SL_KEY_1")
    assert key_1 == ["domain_1"]

    key_2_empty = sl_get_env("SL_KEY_2", default_factory=list)
    assert key_2_empty == []

    with pytest.raises(ValueError):
        sl_get_env("SL_KEY_3")
