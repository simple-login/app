import base64
import json

import itsdangerous
import pytest

from app import config
from app.config import PADDLE_PASSTHROUGH_SECRET
from app.payments.paddle_passthrough import (
    sign_passthrough,
    verify_passthrough,
)


def _tamper(passthrough: str, payload: dict) -> str:
    """replace the payload of a signed passthrough, keeping its signature"""
    _, timestamp, signature = passthrough.split(".")
    forged = (
        base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    )
    return f"{forged}.{timestamp}.{signature}"


def test_sign_verify_round_trip():
    assert verify_passthrough(sign_passthrough(88)) == 88


def test_verify_rejects_tampered_user_id():
    passthrough = sign_passthrough(88)
    assert verify_passthrough(_tamper(passthrough, {"user_id": 99})) is None


def test_verify_rejects_unsigned_legacy_passthrough():
    """the pre-fix format, which the buyer could set freely"""
    assert verify_passthrough('{"user_id": 88 }') is None


def test_verify_rejects_foreign_signature():
    other = itsdangerous.URLSafeTimedSerializer("not-our-secret")
    assert verify_passthrough(other.dumps({"user_id": 88})) is None


def test_verify_rejects_expired_passthrough(monkeypatch):
    monkeypatch.setattr("app.payments.paddle_passthrough._MAX_AGE_SECONDS", -1)
    assert verify_passthrough(sign_passthrough(88)) is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"user_id": None},
        {"user_id": "88"},
        {"user_id": [88]},
        ["user_id", 88],
    ],
)
def test_verify_rejects_payload_without_int_user_id(payload):
    serializer = itsdangerous.URLSafeTimedSerializer(PADDLE_PASSTHROUGH_SECRET)
    assert verify_passthrough(serializer.dumps(payload)) is None


@pytest.mark.parametrize("passthrough", [None, "", "not-a-token"])
def test_verify_rejects_junk(passthrough):
    assert verify_passthrough(passthrough) is None


def test_verify_rejects_boolean_user_id():
    """isinstance(True, int) holds, so True must not resolve to user id 1"""
    serializer = itsdangerous.URLSafeTimedSerializer(PADDLE_PASSTHROUGH_SECRET)
    assert verify_passthrough(serializer.dumps({"user_id": True})) is None


@pytest.fixture
def allow_unsigned(monkeypatch):
    monkeypatch.setattr(config, "PADDLE_ALLOW_UNSIGNED_PASSTHROUGH", True)


def test_legacy_passthrough_accepted_during_transition(allow_unsigned):
    assert verify_passthrough('{"user_id": 88 }') == 88


def test_signed_passthrough_still_works_during_transition(allow_unsigned):
    assert verify_passthrough(sign_passthrough(88)) == 88


def test_transition_does_not_accept_an_expired_signed_passthrough(
    allow_unsigned, monkeypatch
):
    """an expired token must not silently fall through to the legacy path"""
    monkeypatch.setattr("app.payments.paddle_passthrough._MAX_AGE_SECONDS", -1)
    assert verify_passthrough(sign_passthrough(88)) is None


@pytest.mark.parametrize(
    "passthrough",
    [
        "Example String",  # what Paddle's own webhook simulator sends
        "{}",
        '{"user_id": "88"}',
        '{"user_id": true}',
        "[88]",
        '{"user_id": 88',  # truncated json
    ],
)
def test_transition_rejects_junk_legacy_passthrough(allow_unsigned, passthrough):
    assert verify_passthrough(passthrough) is None


def test_legacy_passthrough_rejected_once_the_flag_is_unset(monkeypatch):
    monkeypatch.setattr(config, "PADDLE_ALLOW_UNSIGNED_PASSTHROUGH", False)
    assert verify_passthrough('{"user_id": 88 }') is None
