from app.regex_utils import regex_match, regex_search


def test_regex_match(flask_client):
    assert regex_match("prefix.*", "prefix-abcd")

    # this generates re2 error "Argument 'pattern' has incorrect type (expected bytes, got PythonRePattern)"
    # fallback to re
    assert not regex_match("(?!abcd)s(\\.|-)?([a-z0-9]{4,6})", "abcd")


def test_regex_search_sender_blacklist_patterns(flask_client):
    # Sender blacklist patterns use search semantics and anchor themselves.
    assert regex_search(r"@spam\.test$", "bad@spam.test")
    assert not regex_search(r"@spam\.test$", "bad@spam.test.example.com")
    assert regex_search(r"@(bonjour|csure)\.taxi$", "x@csure.taxi")
    assert regex_search(r"^no-?reply@.*", "noreply@example.com")
    assert not regex_search(r"^no-?reply@.*", "bounce+noreply@example.com")
    assert regex_search(
        r"^([a-z]{4,10}[0-9]{5}|reply)@[a-z]{3,}\.[a-z]{5,}\.(shop|info)$",
        "abcde12345@foo.bargain.shop",
    )
