from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.config import COINBASE_CHECKOUT_ID
from app.dashboard.base import dashboard_bp
from app.models import CoinbaseSubscription


@dashboard_bp.route("/extend_subscription", methods=["GET", "POST"])
@login_required
def extend_subscription_route():
    coinbase_subscription = CoinbaseSubscription.get_by(user_id=current_user.id)
    # this page is only for user who has an active coinbase subscription
    if not coinbase_subscription or not coinbase_subscription.is_active():
        flash("Unknown error, redirect to home page", "error")
        return redirect(url_for("dashboard.index"))

    coinbase_url = "https://commerce.coinbase.com/checkout/" + COINBASE_CHECKOUT_ID

    return render_template(
        "dashboard/extend_subscription.html",
        coinbase_subscription=coinbase_subscription,
        coinbase_url=coinbase_url,
    )
