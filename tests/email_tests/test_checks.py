from email.message import Message

from app.email.checks import check_recipient_limit
from app.email import headers
from tests.utils import random_email


def _email_list(size: int) -> str:
    emails = []
    for i in range(size):
        emails.append(random_email())

    return ", ".join(emails)


def _create_message(to: str, cc: str) -> Message:
    message = Message()
    message[headers.CC] = cc
    message[headers.TO] = to

    return message


def test_can_forward_if_below_limit():
    msg = _create_message(to=_email_list(1), cc=_email_list(1))
    assert check_recipient_limit(msg, 5)


def test_can_forward_if_just_limit():
    msg = _create_message(to=_email_list(1), cc=_email_list(1))
    assert check_recipient_limit(msg, 2)


def test_cannot_forward_if_single_list_above_limit():
    msg = _create_message(to=_email_list(3), cc=_email_list(0))
    assert check_recipient_limit(msg, 2) is False


def test_cannot_forward_if_both_lists_above_limit():
    msg = _create_message(to=_email_list(3), cc=_email_list(3))
    assert check_recipient_limit(msg, 2) is False


def test_cannot_forward_if_both_lists_add_up_to_limit():
    msg = _create_message(to=_email_list(3), cc=_email_list(3))
    assert check_recipient_limit(msg, 5) is False
