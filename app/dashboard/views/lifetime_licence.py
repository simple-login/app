from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import ADMIN_EMAIL
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.email_utils import send_email
from app.models import LifetimeCoupon


class CouponForm(FlaskForm):
    code = StringField("Coupon Code", validators=[validators.DataRequired()])


@dashboard_bp.route("/lifetime_licence", methods=["GET", "POST"])
@login_required
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

        coupon: LifetimeCoupon = LifetimeCoupon.get_by(code=code)
        if coupon and coupon.nb_used > 0:
            coupon.nb_used -= 1
            current_user.lifetime = True
            current_user.lifetime_coupon_id = coupon.id
            if coupon.paid:
                current_user.paid_lifetime = True
            Session.commit()

            # notify admin
            send_email(
                ADMIN_EMAIL,
                subject=f"User {current_user} used lifetime coupon({coupon.comment}). Coupon nb_used: {coupon.nb_used}",
                plaintext="",
                html="",
            )

            flash("You are upgraded to lifetime premium!", "success")
            return redirect(url_for("dashboard.index"))

        else:
            flash(f"Code *{code}* expired or invalid", "warning")

    return render_template("dashboard/lifetime_licence.html", coupon_form=coupon_form)
