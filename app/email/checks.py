from app.email import headers
from app.log import LOG
from email.message import Message
from flanker.addresslib import address


def check_recipient_limit(msg: Message, limit: int) -> bool:
    # Count total recipients in TO and CC
    to_addrs = address.parse_list(str(msg.get(headers.TO, "")))
    cc_addrs = address.parse_list(str(msg.get(headers.CC, "")))
    total_recipients = len(to_addrs) + len(cc_addrs)

    if total_recipients > limit:
        LOG.w(
            f"Too many recipients ({total_recipients}). Max allowed: {limit}. Refusing to forward"
        )
        return False
    return True
