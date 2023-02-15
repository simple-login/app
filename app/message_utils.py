import re
from email import policy
from email.message import Message

from app.log import LOG


def message_to_bytes(msg: Message) -> bytes:
    """replace Message.as_bytes() method by trying different policies"""
    for generator_policy in [None, policy.SMTP, policy.SMTPUTF8]:
        try:
            return msg.as_bytes(policy=generator_policy)
        except:
            LOG.w("as_bytes() fails with %s policy", policy, exc_info=True)

    msg_string = msg.as_string()
    try:
        return msg_string.encode()
    except:
        LOG.w("as_string().encode() fails", exc_info=True)

    return msg_string.encode(errors="replace")


def message_format_base64_parts(msg: Message) -> Message:
    for part in msg.walk():
        if part.get(
            "content-transfer-encoding"
        ) == "base64" and part.get_content_type() in ("text/plain", "text/html"):
            # Remove line breaks
            body = re.sub("[\r\n]", "", part.get_payload())
            # Split in 80 column  lines
            chunks = [body[i : i + 80] for i in range(0, len(body), 80)]
            part.set_payload("\r\n".join(chunks))
    return msg
