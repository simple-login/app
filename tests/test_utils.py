from app.config import ALLOWED_REDIRECT_DOMAINS
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
        {"url": "http://unknown.domain", "expected": None},
        {"url": "https://badzone.org", "expected": None},
        {"url": "/", "expected": "/"},
        {"url": "/auth", "expected": "/auth"},
        {"url": "/some/path", "expected": "/some/path"},
    ]

    for domain in ALLOWED_REDIRECT_DOMAINS:
        cases.append({"url": f"http://{domain}", "expected": f"http://{domain}"})
        cases.append({"url": f"https://{domain}", "expected": f"https://{domain}"})
        cases.append({"url": domain, "expected": None})

    for case in cases:
        res = sanitize_next_url(case["url"])
        assert res == case["expected"]
