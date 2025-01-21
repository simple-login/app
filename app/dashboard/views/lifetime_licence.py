from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import parallel_limiter
from app.coupon_utils import redeem_lifetime_coupon
from app.dashboard.base import dashboard_bp


class CouponForm(FlaskForm):
    code = StringField("Coupon Code", validators=[validators.DataRequired()])


@dashboard_bp.route("/lifetime_licence", methods=["GET", "POST"])
@login_required
@parallel_limiter.lock()
def lifetime_licence():
    if current_user.lifetime:
        flash("You already have a lifetime licence", "warning")
        return redirect(url_for("dashboard.index"))

    # user needs to cancel active subscription first
    # to avoid being charged
    sub = current_user.get_paddle_subscription()
    if sub and not sub.cancelled:
        flash("Please cancel your current subscription first", "warning")
        return redirect(url_for("dashboard.index"))

    coupon_form = CouponForm()

    if coupon_form.validate_on_submit():
        code = coupon_form.code.data
        coupon = redeem_lifetime_coupon(code, current_user)
        if coupon:
            flash("You are upgraded to lifetime premium!", "success")
            return redirect(url_for("dashboard.index"))

        else:
            flash("Coupon code expired or invalid", "warning")

    return render_template("dashboard/lifetime_licence.html", coupon_form=coupon_form)
