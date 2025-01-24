import arrow
import pytest

from app.coupon_utils import (
    redeem_coupon,
    CouponUserCannotRedeemError,
    redeem_lifetime_coupon,
)
from app.models import (
    Coupon,
    Subscription,
    ManualSubscription,
    AppleSubscription,
    CoinbaseSubscription,
    LifetimeCoupon,
    User,
)
from tests.utils import create_new_user, random_string


def test_use_coupon():
    user = create_new_user()
    code = random_string(10)
    Coupon.create(code=code, nb_year=1, commit=True)

    coupon = redeem_coupon(code, user)
    assert coupon

    coupon = Coupon.get_by(code=code)
    assert coupon
    assert coupon.used
    assert coupon.used_by_user_id == user.id

    sub = user.get_active_subscription()
    assert isinstance(sub, ManualSubscription)
    left = sub.end_at - arrow.utcnow()
    assert left.days > 364


def test_use_coupon_extend_manual_sub():
    user = create_new_user()
    initial_end = arrow.now().shift(days=15)
    ManualSubscription.create(
        user_id=user.id,
        end_at=initial_end,
        flush=True,
    )
    code = random_string(10)
    Coupon.create(code=code, nb_year=1, commit=True)

    coupon = redeem_coupon(code, user)
    assert coupon

    coupon = Coupon.get_by(code=code)
    assert coupon
    assert coupon.used
    assert coupon.used_by_user_id == user.id

    sub = user.get_active_subscription()
    assert isinstance(sub, ManualSubscription)
    left = sub.end_at - initial_end
    assert left.days > 364


def test_coupon_with_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=1).replace(hour=0, minute=0, second=0)
    Subscription.create(
        user_id=user.id,
        cancel_url="",
        update_url="",
        subscription_id=random_string(10),
        event_time=arrow.now(),
        next_bill_date=end_at.date(),
        plan="yearly",
        flush=True,
    )
    with pytest.raises(CouponUserCannotRedeemError):
        redeem_coupon("", user)


def test_webhook_with_apple_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=2).replace(hour=0, minute=0, second=0)
    AppleSubscription.create(
        user_id=user.id,
        receipt_data=arrow.now().date().strftime("%Y-%m-%d"),
        expires_date=end_at.date().strftime("%Y-%m-%d"),
        original_transaction_id=random_string(10),
        plan="yearly",
        product_id="",
        flush=True,
    )
    with pytest.raises(CouponUserCannotRedeemError):
        redeem_coupon("", user)


def test_webhook_with_coinbase_subscription():
    user = create_new_user()
    end_at = arrow.utcnow().shift(days=3).replace(hour=0, minute=0, second=0)
    CoinbaseSubscription.create(
        user_id=user.id, end_at=end_at.date().strftime("%Y-%m-%d"), flush=True
    )

    with pytest.raises(CouponUserCannotRedeemError):
        redeem_coupon("", user)


def test_expired_coupon():
    user = create_new_user()
    code = random_string(10)
    Coupon.create(
        code=code, nb_year=1, commit=True, expires_date=arrow.utcnow().shift(days=-1)
    )

    coupon = redeem_coupon(code, user)
    assert coupon is None


def test_used_coupon():
    user = create_new_user()
    code = random_string(10)
    Coupon.create(code=code, nb_year=1, commit=True, used=True)
    coupon = redeem_coupon(code, user)
    assert coupon is None


# Lifetime
def test_lifetime_coupon():
    user = create_new_user()
    code = random_string(10)
    LifetimeCoupon.create(code=code, nb_used=1)
    coupon = redeem_lifetime_coupon(code, user)
    assert coupon
    user = User.get(user.id)
    assert user.lifetime
    assert not user.paid_lifetime


def test_lifetime_paid_coupon():
    user = create_new_user()
    code = random_string(10)
    LifetimeCoupon.create(code=code, nb_used=1, paid=True)
    coupon = redeem_lifetime_coupon(code, user)
    assert coupon
    user = User.get(user.id)
    assert user.lifetime
    assert user.paid_lifetime


def test_used_lifetime_coupon():
    user = create_new_user()
    code = random_string(10)
    LifetimeCoupon.create(code=code, nb_used=0, paid=True)
    coupon = redeem_lifetime_coupon(code, user)
    assert coupon is None
    user = User.get(user.id)
    assert not user.lifetime
    assert not user.paid_lifetime
