import asyncio
import time
from email.message import Message

import aiospamc

from app.config import SPAMASSASSIN_HOST
from app.log import LOG
from app.message_utils import message_to_bytes
from app.models import EmailLog
from app.spamassassin_utils import SpamAssassin


async def get_spam_score_async(message: Message) -> float:
    sa_input = message_to_bytes(message)

    # Spamassassin requires to have an ending linebreak
    if not sa_input.endswith(b"\n"):
        LOG.d("add linebreak to spamassassin input")
        sa_input += b"\n"

    try:
        # wait for at max 300s which is the default spamd timeout-child
        response = await asyncio.wait_for(
            aiospamc.check(sa_input, host=SPAMASSASSIN_HOST), timeout=300
        )
        return response.headers["Spam"].score
    except asyncio.TimeoutError:
        LOG.e("SpamAssassin timeout")
        # return a negative score so the message is always considered as ham
        return -999
    except Exception:
        LOG.e("SpamAssassin exception")
        return -999


def get_spam_score(
    message: Message, email_log: EmailLog, can_retry=True
) -> (float, dict):
    """
    Return the spam score and spam report
    """
    LOG.d("get spam score for %s", email_log)
    sa_input = message_to_bytes(message)

    # Spamassassin requires to have an ending linebreak
    if not sa_input.endswith(b"\n"):
        LOG.d("add linebreak to spamassassin input")
        sa_input += b"\n"

    try:
        # wait for at max 300s which is the default spamd timeout-child
        sa = SpamAssassin(sa_input, host=SPAMASSASSIN_HOST, timeout=300)
        return sa.get_score(), sa.get_report_json()
    except Exception:
        if can_retry:
            LOG.w("SpamAssassin exception, retry")
            time.sleep(3)
            return get_spam_score(message, email_log, can_retry=False)
        else:
            # return a negative score so the message is always considered as ham
            LOG.e("SpamAssassin exception, ignore spam check")
            return -999, None
