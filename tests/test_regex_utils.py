from app.regex_utils import regex_match


def test_regex_match(flask_client):
    assert regex_match("prefix.*", "prefix-abcd")

    # this generates re2 error "Argument 'pattern' has incorrect type (expected bytes, got PythonRePattern)"
    # fallback to re
    assert not regex_match("(?!abcd)s(\\.|-)?([a-z0-9]{4,6})", "abcd")
