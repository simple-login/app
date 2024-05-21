import requests
from requests import RequestException

from app import config
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChange
from app.log import LOG
from app.models import User


def execute_subscription_webhook(user: User):
    webhook_url = config.SUBSCRIPTION_CHANGE_WEBHOOK
    if webhook_url is None:
        return
    subscription_end = user.get_active_subscription_end(
        include_partner_subscription=False
    )
    sl_subscription_end = None
    if subscription_end:
        sl_subscription_end = subscription_end.timestamp
    payload = {
        "user_id": user.id,
        "is_premium": user.is_premium(),
        "active_subscription_end": sl_subscription_end,
    }
    try:
        response = requests.post(webhook_url, json=payload, timeout=2)
        if response.status_code == 200:
            LOG.i("Sent request to subscription update webhook successfully")
        else:
            LOG.i(
                f"Request to webhook failed with statue {response.status_code}: {response.text}"
            )
    except RequestException as e:
        LOG.error(f"Subscription request exception: {e}")

    event = UserPlanChange(plan_end_time=sl_subscription_end)
    EventDispatcher.send_event(user, EventContent(user_plan_change=event))
