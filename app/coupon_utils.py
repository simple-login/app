from typing import Optional

import arrow
from sqlalchemy import or_, update, and_

from app.config import ADMIN_EMAIL
from app.db import Session
from app.email_utils import send_email
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.log import LOG
from app.models import (
    User,
    ManualSubscription,
    Coupon,
    LifetimeCoupon,
    PartnerSubscription,
    PartnerUser,
)
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

    coupon = Coupon.get_by(code=coupon_code)
    if not coupon:
        LOG.i(f"User is trying to redeem coupon {coupon_code} that does not exist")
        return None

    now = arrow.utcnow()
    stmt = (
        update(Coupon)
        .where(
            and_(
                Coupon.code == coupon_code,
                Coupon.used == False,  # noqa: E712
                or_(
                    Coupon.expires_date == None,  # noqa: E711
                    Coupon.expires_date > now,
                ),
            )
        )
        .values(used=True, used_by_user_id=user.id, updated_at=now)
    )
    res = Session.execute(stmt)
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
    if user.lifetime:
        return None
    partner_sub = (
        Session.query(PartnerSubscription)
        .join(PartnerUser, PartnerUser.id == PartnerSubscription.partner_user_id)
        .filter(PartnerUser.user_id == user.id, PartnerSubscription.lifetime == True)  # noqa: E712
        .first()
    )
    if partner_sub is not None:
        return None
    coupon: LifetimeCoupon = LifetimeCoupon.get_by(code=coupon_code)
    if not coupon:
        return None

    stmt = (
        update(LifetimeCoupon)
        .where(
            and_(
                LifetimeCoupon.code == coupon_code,
                LifetimeCoupon.nb_used > 0,
            )
        )
        .values(nb_used=LifetimeCoupon.nb_used - 1)
    )
    res = Session.execute(stmt)
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
