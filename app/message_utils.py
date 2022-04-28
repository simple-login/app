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
