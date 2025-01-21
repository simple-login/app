from typing import Optional

import arrow

from app.config import ADMIN_EMAIL
from app.db import Session
from app.email_utils import send_email
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.log import LOG
from app.models import User, ManualSubscription, Coupon, LifetimeCoupon
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


class CouponUserCannotRedeemError(Exception):
    pass


def redeem_coupon(coupon_code: str, user: User) -> Optional[Coupon]:
    if user.lifetime:
        LOG.i(f"User {user} is a lifetime SL user. Cannot redeem coupons")
        raise CouponUserCannotRedeemError()

    sub = user.get_active_subscription()
    if sub and not isinstance(sub, ManualSubscription):
        LOG.i(
            f"User {user} has an active subscription that is not manual. Cannot redeem coupon {coupon_code}"
        )
        raise CouponUserCannotRedeemError()

    coupon = Session.query(Coupon).filter(Coupon.code == coupon_code).one()
    if not coupon:
        LOG.i(f"User is trying to redeem coupon {coupon_code} that does not exist")
        return None

    sql = """
        UPDATE "coupon"
        SET used = True, used_by_user_id = :user_id, updated_at = now()
        WHERE code = :code AND used = False and (expires_date IS NULL OR expires_date > now())
    """
    res = Session.execute(sql, {"code": coupon_code, "user_id": user.id})
    if res.rowcount == 0:
        LOG.i(f"Coupon {coupon.id} could not be redeemed. It's expired or invalid.")
        return None

    LOG.i(
        f"Redeemed normal coupon {coupon.id} for {coupon.nb_year} years by user {user}"
    )
    if sub:
        # renew existing subscription
        if sub.end_at > arrow.now():
            sub.end_at = sub.end_at.shift(years=coupon.nb_year)
        else:
            sub.end_at = arrow.now().shift(years=coupon.nb_year, days=1)
    else:
        sub = ManualSubscription.create(
            user_id=user.id,
            end_at=arrow.now().shift(years=coupon.nb_year, days=1),
            comment="using coupon code",
            is_giveaway=coupon.is_giveaway,
            commit=True,
        )
    emit_user_audit_log(
        user=user,
        action=UserAuditLogAction.Upgrade,
        message=f"User {user} redeemed coupon {coupon.id} for {coupon.nb_year} years",
    )
    EventDispatcher.send_event(
        user=user,
        content=EventContent(
            user_plan_change=UserPlanChanged(plan_end_time=sub.end_at.timestamp)
        ),
    )
    Session.commit()
    return coupon


def redeem_lifetime_coupon(coupon_code: str, user: User) -> Optional[Coupon]:
    coupon: LifetimeCoupon = LifetimeCoupon.get_by(code=coupon_code)
    if not coupon:
        return None

    sql = 'UPDATE "lifetime_coupon" SET nb_used = nb_used -1 where nb_used >0 and "code" = :code'
    res = Session.execute(sql, {"code": coupon_code})
    if res.rowcount == 0:
        LOG.i("Coupon could not be redeemed")
        return None

    user.lifetime = True
    user.lifetime_coupon_id = coupon.id
    if coupon.paid:
        user.paid_lifetime = True
    EventDispatcher.send_event(
        user=user,
        content=EventContent(user_plan_change=UserPlanChanged(lifetime=True)),
    )
    Session.commit()

    # notify admin
    send_email(
        ADMIN_EMAIL,
        subject=f"User {user} used lifetime coupon({coupon.comment}). Coupon nb_used: {coupon.nb_used}",
        plaintext="",
        html="",
    )

    return coupon
