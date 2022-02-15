from app.utils import random_string, random_words, sanitize_next_url


def test_random_words():
    s = random_words()
    assert len(s) > 0


def test_random_string():
    s = random_string()
    assert len(s) > 0


def test_sanitize_url():
    cases = [
        {"url": None, "expected": None},
        {"url": "", "expected": None},
        {"url": "https://badzone.org", "expected": None},
        {"url": "/", "expected": "/"},
        {"url": "/auth", "expected": "/auth"},
        {"url": "/some/path", "expected": "/some/path"},
    ]

    for case in cases:
        res = sanitize_next_url(case["url"])
        assert res == case["expected"]
