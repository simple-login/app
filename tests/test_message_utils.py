import email
from app.email_utils import (
    copy,
)
from app.message_utils import message_to_bytes


def test_copy():
    email_str = """
    From: abcd@gmail.com
    To: hey@example.org
    Subject: subject

    Body
    """
    msg = email.message_from_string(email_str)
    msg2 = copy(msg)
    assert message_to_bytes(msg) == message_to_bytes(msg2)

    msg = email.message_from_string("👌")
    msg2 = copy(msg)
    assert message_to_bytes(msg) == message_to_bytes(msg2)


def test_to_bytes():
    msg = email.message_from_string("☕️ emoji")
    assert message_to_bytes(msg)
    # \n is appended when message is converted to bytes
    assert message_to_bytes(msg).decode() == "\n☕️ emoji"

    msg = email.message_from_string("ascii")
    assert message_to_bytes(msg) == b"\nascii"

    msg = email.message_from_string("éèà€")
    assert message_to_bytes(msg).decode() == "\néèà€"
