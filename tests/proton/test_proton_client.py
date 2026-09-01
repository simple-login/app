import pytest
from http import HTTPStatus

from app.errors import ProtonAccountNotVerified
from app.proton import proton_client


def test_convert_access_token_valid():
    res = proton_client.convert_access_token("pt-abc-123")
    assert res.session_id == "abc"
    assert res.access_token == "123"


def test_convert_access_token_not_containing_pt():
    with pytest.raises(Exception):
        proton_client.convert_access_token("pb-abc-123")


def test_convert_access_token_too_short():
    with pytest.raises(Exception):
        proton_client.convert_access_token("pt-short")


def test_convert_access_token_with_many_hyphens():
    res = proton_client.convert_access_token("pt-abc-part1-part2-part3")
    assert res.session_id == "abc"
    assert res.access_token == "part1-part2-part3"


def test_convert_access_token_real_jwt_example():
    token_response = "pt-gj7m3zauijwvltko4d6xr5rskfq25j34-eyJpdiI6ImdTMjdYU1B.rbVN4d-mx2QnYiLCJ0YWciOi-JlMlAwT0FQVG_tWUW5kUzF-yUEQzZFJBIiwi"
    res = proton_client.convert_access_token(token_response)
    assert res.session_id == "gj7m3zauijwvltko4d6xr5rskfq25j34"
    assert (
        res.access_token
        == "eyJpdiI6ImdTMjdYU1B.rbVN4d-mx2QnYiLCJ0YWciOi-JlMlAwT0FQVG_tWUW5kUzF-yUEQzZFJBIiwi"
    )


def test_handle_response_not_ok_account_not_verified():
    res = proton_client.handle_response_not_ok(
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        body={"Code": proton_client.PROTON_ERROR_CODE_HV_NEEDED},
        text="",
    )
    assert isinstance(res, ProtonAccountNotVerified)


def test_handle_response_unprocessable_entity_not_account_not_verified():
    error_text = "some error text"
    res = proton_client.handle_response_not_ok(
        status=HTTPStatus.UNPROCESSABLE_ENTITY, body={"Code": 4567}, text=error_text
    )
    assert error_text in res.args[0]


def test_handle_response_not_ok_unknown_error():
    error_text = "some error text"
    res = proton_client.handle_response_not_ok(
        status=123,
        body={"Code": proton_client.PROTON_ERROR_CODE_HV_NEEDED},
        text=error_text,
    )
    assert error_text in res.args[0]
