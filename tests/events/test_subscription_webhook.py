import arrow

from app import config
from app.events.event_dispatcher import GlobalDispatcher
from app.events.generated.event_pb2 import UserPlanChanged
from app.models import (
    Subscription,
    AppleSubscription,
    CoinbaseSubscription,
    ManualSubscription,
    User,
    PartnerUser,
)

from .event_test_utils import (
    OnMemoryDispatcher,
    _create_linked_user,
    _get_event_from_string,
)
from tests.utils import random_token

from app.subscription_webhook import execute_subscription_webhook


on_memory_dispatcher = OnMemoryDispatcher()


def setup_module():
    GlobalDispatcher.set_dispatcher(on_memory_dispatcher)
    config.EVENT_WEBHOOK = "http://test"


def teardown_module():
    GlobalDispatcher.set_dispatcher(None)
    config.EVENT_WEBHOOK = None


def setup_function(func):
    on_memory_dispatcher.clear()


def check_event(user: User, pu: PartnerUser) -> UserPlanChanged:
    assert len(on_memory_dispatcher.memory) == 1
    event_data = on_memory_dispatcher.memory[0]
    event_content = _get_event_from_string(event_data, user, pu)
    assert event_content.user_plan_change is not None
    plan_change = event_content.user_plan_change
    return plan_change


def test_webhook_with_trial():
    (user, pu) = _create_linked_user()
    execute_subscription_webhook(user)
    assert check_event(user, pu).plan_end_time == 0


def test_webhook_with_subscription():
    (user, pu) = _create_linked_user()
    end_at = arrow.utcnow().shift(days=1).replace(hour=0, minute=0, second=0)
    Subscription.create(
        user_id=user.id,
        cancel_url="",
        update_url="",
        subscription_id=random_token(10),
        event_time=arrow.now(),
        next_bill_date=end_at.date(),
        plan="yearly",
        flush=True,
    )
    execute_subscription_webhook(user)
    assert check_event(user, pu).plan_end_time == end_at.timestamp


def test_webhook_with_apple_subscription():
    (user, pu) = _create_linked_user()
    end_at = arrow.utcnow().shift(days=2).replace(hour=0, minute=0, second=0)
    AppleSubscription.create(
        user_id=user.id,
        receipt_data=arrow.now().date().strftime("%Y-%m-%d"),
        expires_date=end_at.date().strftime("%Y-%m-%d"),
        original_transaction_id=random_token(10),
        plan="yearly",
        product_id="",
        flush=True,
    )
    execute_subscription_webhook(user)
    assert check_event(user, pu).plan_end_time == end_at.timestamp


def test_webhook_with_coinbase_subscription():
    (user, pu) = _create_linked_user()
    end_at = arrow.utcnow().shift(days=3).replace(hour=0, minute=0, second=0)
    CoinbaseSubscription.create(
        user_id=user.id, end_at=end_at.date().strftime("%Y-%m-%d"), flush=True
    )

    execute_subscription_webhook(user)
    assert check_event(user, pu).plan_end_time == end_at.timestamp


def test_webhook_with_manual_subscription():
    (user, pu) = _create_linked_user()
    end_at = arrow.utcnow().shift(days=3).replace(hour=0, minute=0, second=0)
    ManualSubscription.create(
        user_id=user.id, end_at=end_at.date().strftime("%Y-%m-%d"), flush=True
    )

    execute_subscription_webhook(user)
    assert check_event(user, pu).plan_end_time == end_at.timestamp
