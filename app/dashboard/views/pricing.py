import arrow
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
from app.models import (
    AppleSubscription,
    Subscription,
    ManualSubscription,
    CoinbaseSubscription,
)


@dashboard_bp.route("/pricing", methods=["GET", "POST"])
@login_required
def pricing():
    if current_user.lifetime:
        flash("You already have a lifetime subscription", "error")
        return redirect(url_for("dashboard.index"))

    sub: Subscription = current_user.get_subscription()
    # user who has canceled can re-subscribe
    if sub and not sub.cancelled:
        flash("You already have an active subscription", "error")
        return redirect(url_for("dashboard.index"))

    now = arrow.now()
    manual_sub: ManualSubscription = ManualSubscription.filter(
        ManualSubscription.user_id == current_user.id, ManualSubscription.end_at > now
    ).first()

    coinbase_sub = CoinbaseSubscription.filter(
        CoinbaseSubscription.user_id == current_user.id,
        CoinbaseSubscription.end_at > now,
    ).first()

    apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=current_user.id)
    if apple_sub and apple_sub.is_valid():
        flash("Please make sure to cancel your subscription on Apple first", "warning")

    return render_template(
        "dashboard/pricing.html",
        PADDLE_VENDOR_ID=PADDLE_VENDOR_ID,
        PADDLE_MONTHLY_PRODUCT_ID=PADDLE_MONTHLY_PRODUCT_ID,
        PADDLE_YEARLY_PRODUCT_ID=PADDLE_YEARLY_PRODUCT_ID,
        success_url=URL + "/dashboard/subscription_success",
        manual_sub=manual_sub,
        coinbase_sub=coinbase_sub,
        now=now,
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
