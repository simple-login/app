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


def test_convert_access_token_not_containing_invalid_length():
    cases = ["pt-abc-too-long", "pt-short"]
    for case in cases:
        with pytest.raises(Exception):
            proton_client.convert_access_token(case)


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
