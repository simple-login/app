from app.utils import random_string, random_words, suggest_prefix


def test_random_words():
    s = random_words()
    assert len(s) > 0


def test_random_string():
    s = random_string()
    assert len(s) > 0

def test_suggest_prefix():
    case_0 = "github.com"
    expected_0 = "github"

    case_1 = "www.simplelogin.io"
    expected_1 = "simplelogin"

    case_co_0 = "bbc.co.uk"
    expected_co_0 = "bbc"

    case_co_1 = "www.co.fr"
    expected_co_1 = "co"

    assert suggest_prefix(case_0) == expected_0
    assert suggest_prefix(case_1) == expected_1
    assert suggest_prefix(case_co_0) == expected_co_0
    assert suggest_prefix(case_co_1) == expected_co_1