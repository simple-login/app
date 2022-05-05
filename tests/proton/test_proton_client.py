import pytest

from app.proton import proton_client


def test_convert_access_token_valid():
    res = proton_client.convert_access_token("pt-abc-123")
    assert res.session_id == "abc"
    assert res.access_token == "123"


def test_convert_access_token_not_containing_pt():
    with pytest.raises(Exception):
        proton_client.convert_access_token("pb-abc-123")


def test_convert_access_token_not_containing_invalid_length():
    cases = ["pt-abc-too-long", "pt-short"]
    for case in cases:
        with pytest.raises(Exception):
            proton_client.convert_access_token(case)
