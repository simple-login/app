import pytest

from app.handler.unsubscribe_encoder import (
    UnsubscribeData,
    UnsubscribeAction,
    UnsubscribeEncoder,
)

legacy_test_data = [
    ("3=", UnsubscribeData(UnsubscribeAction.DisableAlias, 3)),
    ("438_", UnsubscribeData(UnsubscribeAction.DisableContact, 438)),
    ("4325*", UnsubscribeData(UnsubscribeAction.UnsubscribeNewsletter, 4325)),
]


@pytest.mark.parametrize("serialized_data, expected", legacy_test_data)
def test_decode_legacy_unsub(serialized_data, expected):
    info = UnsubscribeEncoder.decode(serialized_data)
    assert expected == info


encode_decode_test_data = [
    UnsubscribeData(UnsubscribeAction.DisableContact, 3),
    UnsubscribeData(UnsubscribeAction.DisableContact, 10),
    UnsubscribeData(UnsubscribeAction.DisableAlias, 101),
]


@pytest.mark.parametrize("unsub_data", encode_decode_test_data)
def test_encode_decode_unsub(unsub_data):
    encoded = UnsubscribeEncoder.encode(unsub_data)
    decoded = UnsubscribeEncoder.decode(encoded)
    assert unsub_data.action == decoded.action
    assert unsub_data.data == decoded.data
