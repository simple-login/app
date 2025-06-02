from app.db import Session
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.models import User


def execute_subscription_webhook(user: User):
    subscription_end = user.get_active_subscription_end(
        include_partner_subscription=False
    )
    sl_subscription_end = None
    if subscription_end:
        sl_subscription_end = subscription_end.timestamp
    event = UserPlanChanged(plan_end_time=sl_subscription_end)
    EventDispatcher.send_event(user, EventContent(user_plan_change=event))
    Session.commit()
