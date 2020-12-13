from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.config import (
    PADDLE_VENDOR_ID,
    PADDLE_MONTHLY_PRODUCT_ID,
    PADDLE_YEARLY_PRODUCT_ID,
    URL,
    COINBASE_CHECKOUT_ID,
)
from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/pricing", methods=["GET", "POST"])
@login_required
def pricing():
    if not current_user.can_upgrade():
        flash("You are already a premium user", "warning")
        return redirect(url_for("dashboard.index"))

    coinbase_url = "https://commerce.coinbase.com/checkout/" + COINBASE_CHECKOUT_ID

    return render_template(
        "dashboard/pricing.html",
        PADDLE_VENDOR_ID=PADDLE_VENDOR_ID,
        PADDLE_MONTHLY_PRODUCT_ID=PADDLE_MONTHLY_PRODUCT_ID,
        PADDLE_YEARLY_PRODUCT_ID=PADDLE_YEARLY_PRODUCT_ID,
        success_url=URL + "/dashboard/subscription_success",
        coinbase_url=coinbase_url,
    )


@dashboard_bp.route("/subscription_success")
@login_required
def subscription_success():
    flash("Thanks so much for supporting SimpleLogin!", "success")
    return redirect(url_for("dashboard.index"))
