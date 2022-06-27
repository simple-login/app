import pytest

from app import config
from app.handler.unsubscribe_encoder import (
    UnsubscribeData,
    UnsubscribeAction,
    UnsubscribeEncoder,
)

legacy_subject_test_data = [
    ("3=", UnsubscribeData(UnsubscribeAction.DisableAlias, 3)),
    ("438_", UnsubscribeData(UnsubscribeAction.DisableContact, 438)),
    ("4325*", UnsubscribeData(UnsubscribeAction.UnsubscribeNewsletter, 4325)),
]


@pytest.mark.parametrize("expected_subject, expected_deco", legacy_subject_test_data)
def test_legacy_unsub_subject(expected_subject, expected_deco):
    info = UnsubscribeEncoder.decode_subject(expected_subject)
    assert expected_deco == info
    subject = UnsubscribeEncoder.encode_subject(
        expected_deco.action, expected_deco.data
    )
    assert expected_subject == subject


legacy_url_test_data = [
    (
        f"{config.URL}/dashboard/unsubscribe/3",
        UnsubscribeData(UnsubscribeAction.DisableAlias, 3),
    ),
    (
        f"{config.URL}/dashboard/block_contact/5",
        UnsubscribeData(UnsubscribeAction.DisableContact, 5),
    ),
]


@pytest.mark.parametrize("expected_url, unsub_data", legacy_url_test_data)
def test_encode_decode_unsub_subject(expected_url, unsub_data):
    url = UnsubscribeEncoder.encode_url(unsub_data.action, unsub_data.data)
    assert expected_url == url


legacy_mail_or_link_test_data = [
    (
        f"{config.URL}/dashboard/unsubscribe/3",
        False,
        UnsubscribeData(UnsubscribeAction.DisableAlias, 3),
    ),
    (
        "mailto:me@nowhere.net?subject=9=",
        True,
        UnsubscribeData(UnsubscribeAction.DisableAlias, 9),
    ),
    (
        f"{config.URL}/dashboard/block_contact/8",
        False,
        UnsubscribeData(UnsubscribeAction.DisableContact, 8),
    ),
    (
        "mailto:me@nowhere.net?subject=8_",
        True,
        UnsubscribeData(UnsubscribeAction.DisableContact, 8),
    ),
    (
        "mailto:me@nowhere.net?subject=83*",
        True,
        UnsubscribeData(UnsubscribeAction.UnsubscribeNewsletter, 83),
    ),
]


@pytest.mark.parametrize(
    "expected_link, via_mail, unsub_data", legacy_mail_or_link_test_data
)
def test_encode_legacy_link(expected_link, via_mail, unsub_data):
    if via_mail:
        config.UNSUBSCRIBER = "me@nowhere.net"
    else:
        config.UNSUBSCRIBER = None
    link_info = UnsubscribeEncoder.encode(unsub_data.action, unsub_data.data)
    assert via_mail == link_info.via_email
    assert expected_link == link_info.link
