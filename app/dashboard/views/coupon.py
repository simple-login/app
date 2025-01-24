import arrow
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import parallel_limiter
from app.config import PADDLE_VENDOR_ID, PADDLE_COUPON_ID
from app.coupon_utils import redeem_coupon, CouponUserCannotRedeemError
from app.dashboard.base import dashboard_bp
from app.log import LOG
from app.models import (
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
        try:
            coupon = redeem_coupon(code, current_user)
            if coupon:
                flash(
                    "Your account has been upgraded to Premium, thanks for your support!",
                    "success",
                )
            else:
                flash(
                    "This coupon cannot be redeemed. It's invalid or has expired",
                    "warning",
                )
        except CouponUserCannotRedeemError:
            flash(
                "You have an active subscription. Please remove it before redeeming a coupon",
                "warning",
            )

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
