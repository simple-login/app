import arrow

from app.db import Session
from app.email_utils import send_email, render
from app.log import LOG
from app.models import Subscription
from app import paddle_utils


def failed_payment(sub: Subscription, subscription_id: str):
    LOG.w(
        "Subscription failed payment %s for %s (sub %s)",
        subscription_id,
        sub.user,
        sub.id,
    )

    sub.cancelled = True
    Session.commit()

    user = sub.user

    paddle_utils.cancel_subscription(subscription_id)

    send_email(
        user.email,
        "SimpleLogin - your subscription has failed to be renewed",
        render(
            "transactional/subscription-cancel.txt",
            end_date=arrow.arrow.datetime.utcnow(),
        ),
    )
