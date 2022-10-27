import arrow
from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import parallel_limiter
from app.config import PADDLE_VENDOR_ID, PADDLE_COUPON_ID
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.models import (
    ManualSubscription,
    Coupon,
    Subscription,
    AppleSubscription,
    CoinbaseSubscription,
    LifetimeCoupon,
)


class CouponForm(FlaskForm):
    code = StringField("Coupon Code", validators=[validators.DataRequired()])


@dashboard_bp.route("/coupon", methods=["GET", "POST"])
@login_required
@parallel_limiter.lock()
def coupon_route():
    coupon_form = CouponForm()

    if coupon_form.validate_on_submit():
        code = coupon_form.code.data
        if LifetimeCoupon.get_by(code=code):
            LOG.d("redirect %s to lifetime page instead", current_user)
            flash("Redirect to the lifetime coupon page instead", "success")
            return redirect(url_for("dashboard.lifetime_licence"))

    # handle case user already has an active subscription via another channel (Paddle, Apple, etc)
    can_use_coupon = True

    if current_user.lifetime:
        can_use_coupon = False

    sub: Subscription = current_user.get_paddle_subscription()
    if sub:
        can_use_coupon = False

    apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=current_user.id)
    if apple_sub and apple_sub.is_valid():
        can_use_coupon = False

    coinbase_subscription: CoinbaseSubscription = CoinbaseSubscription.get_by(
        user_id=current_user.id
    )
    if coinbase_subscription and coinbase_subscription.is_active():
        can_use_coupon = False

    if coupon_form.validate_on_submit():
        code = coupon_form.code.data

        coupon: Coupon = Coupon.get_by(code=code)
        if coupon and not coupon.used:
            if coupon.expires_date and coupon.expires_date < arrow.now():
                flash(
                    f"The coupon was expired on {coupon.expires_date.humanize()}",
                    "error",
                )
                return redirect(request.url)

            coupon.used_by_user_id = current_user.id
            coupon.used = True
            Session.commit()

            manual_sub: ManualSubscription = ManualSubscription.get_by(
                user_id=current_user.id
            )
            if manual_sub:
                # renew existing subscription
                if manual_sub.end_at > arrow.now():
                    manual_sub.end_at = manual_sub.end_at.shift(years=coupon.nb_year)
                else:
                    manual_sub.end_at = arrow.now().shift(years=coupon.nb_year, days=1)
                Session.commit()
                flash(
                    f"Your current subscription is extended to {manual_sub.end_at.humanize()}",
                    "success",
                )
            else:
                ManualSubscription.create(
                    user_id=current_user.id,
                    end_at=arrow.now().shift(years=coupon.nb_year, days=1),
                    comment="using coupon code",
                    is_giveaway=coupon.is_giveaway,
                    commit=True,
                )
                flash(
                    f"Your account has been upgraded to Premium, thanks for your support!",
                    "success",
                )

            return redirect(url_for("dashboard.index"))

        else:
            flash(f"Code *{code}* expired or invalid", "warning")

    return render_template(
        "dashboard/coupon.html",
        coupon_form=coupon_form,
        PADDLE_VENDOR_ID=PADDLE_VENDOR_ID,
        PADDLE_COUPON_ID=PADDLE_COUPON_ID,
        can_use_coupon=can_use_coupon,
        # a coupon is only valid until this date
        # this is to avoid using the coupon to renew an account forever
        max_coupon_date=arrow.now().shift(years=1, days=-1),
    )
