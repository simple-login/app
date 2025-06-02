import email
from app.email_utils import (
    copy,
)
from app.message_utils import message_to_bytes, message_format_base64_parts
from tests.utils import load_eml_file


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


def test_base64_line_breaks():
    msg = load_eml_file("bad_base64format.eml")
    msg = message_format_base64_parts(msg)
    for part in msg.walk():
        if part.get("content-transfer-encoding") == "base64":
            body = part.get_payload()
            for line in body.splitlines():
                assert len(line) <= 76
