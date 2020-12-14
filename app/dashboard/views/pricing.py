from coinbase_commerce import Client
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.config import (
    PADDLE_VENDOR_ID,
    PADDLE_MONTHLY_PRODUCT_ID,
    PADDLE_YEARLY_PRODUCT_ID,
    URL,
    COINBASE_YEARLY_PRICE,
    COINBASE_API_KEY,
)
from app.dashboard.base import dashboard_bp
from app.log import LOG


@dashboard_bp.route("/pricing", methods=["GET", "POST"])
@login_required
def pricing():
    if not current_user.can_upgrade():
        flash("You are already a premium user", "warning")
        return redirect(url_for("dashboard.index"))

    return render_template(
        "dashboard/pricing.html",
        PADDLE_VENDOR_ID=PADDLE_VENDOR_ID,
        PADDLE_MONTHLY_PRODUCT_ID=PADDLE_MONTHLY_PRODUCT_ID,
        PADDLE_YEARLY_PRODUCT_ID=PADDLE_YEARLY_PRODUCT_ID,
        success_url=URL + "/dashboard/subscription_success",
    )


@dashboard_bp.route("/subscription_success")
@login_required
def subscription_success():
    flash("Thanks so much for supporting SimpleLogin!", "success")
    return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/coinbase_checkout")
@login_required
def coinbase_checkout_route():
    client = Client(api_key=COINBASE_API_KEY)
    charge = client.charge.create(
        name="1 Year SimpleLogin Premium Subscription",
        local_price={"amount": str(COINBASE_YEARLY_PRICE), "currency": "USD"},
        pricing_type="fixed_price",
        metadata={"user_id": current_user.id},
    )

    LOG.d("Create coinbase charge %s", charge)

    return redirect(charge["hosted_url"])
