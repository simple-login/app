from typing import List, Optional
from urllib.parse import parse_qs

import pytest

from app.config import ALLOWED_REDIRECT_DOMAINS
from app.utils import random_string, random_words, sanitize_next_url, canonicalize_email


def test_random_words():
    s = random_words()
    assert s.find("_") > 0
    assert s.count("_") == 1
    assert len(s) > 3
    s = random_words(2, 3)
    assert s.count("_") == 1
    assert s[-1] in (str(i) for i in range(10))


def test_random_string():
    s = random_string()
    assert len(s) > 0


def generate_sanitize_url_cases() -> List:
    cases = [
        [None, None],
        ["", None],
        ["http://badhttp.com", None],
        ["https://badhttps.com", None],
        ["/", "/"],
        ["/auth", "/auth"],
        ["/some/path", "/some/path"],
        ["//somewhere.net", None],
        ["//\\\\evil.com", None],
    ]
    for domain in ALLOWED_REDIRECT_DOMAINS:
        cases.append([f"http://{domain}", f"http://{domain}"])
        cases.append([f"https://{domain}", f"https://{domain}"])
        cases.append([f"https://{domain}/sub", f"https://{domain}/sub"])
        cases.append([domain, None])
        cases.append([f"//{domain}", f"//{domain}"])
        cases.append([f"https://google.com\\@{domain}/haha", None])
    return cases


@pytest.mark.parametrize("url,expected", generate_sanitize_url_cases())
def test_sanitize_url(url: str, expected: Optional[str]):
    sanitized = sanitize_next_url(url)
    assert expected == sanitized


def test_parse_querystring():
    cases = [
        {"input": "", "expected": {}},
        {"input": "a=b", "expected": {"a": ["b"]}},
        {"input": "a=b&c=d", "expected": {"a": ["b"], "c": ["d"]}},
        {"input": "a=b&a=c", "expected": {"a": ["b", "c"]}},
    ]

    for case in cases:
        expected = case["expected"]
        res = parse_qs(case["input"])
        assert len(res) == len(expected)
        for k, v in expected.items():
            assert res[k] == v


def canonicalize_email_cases():
    for domain in ("gmail.com", "protonmail.com", "proton.me", "pm.me"):
        yield (f"a@{domain}", f"a@{domain}")
        yield (f"a.b@{domain}", f"ab@{domain}")
        yield (f"a.b+c@{domain}", f"ab@{domain}")
        yield ("a.b+c@other.com", "a.b+c@other.com")


@pytest.mark.parametrize("dirty,clean", canonicalize_email_cases())
def test_canonicalize_email(dirty: str, clean: str):
    assert canonicalize_email(dirty) == clean
