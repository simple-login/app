from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.config import (
    PADDLE_VENDOR_ID,
    PADDLE_MONTHLY_PRODUCT_ID,
    PADDLE_YEARLY_PRODUCT_ID,
    URL,
)
from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/pricing", methods=["GET", "POST"])
@login_required
def pricing():
    # sanity check: make sure this page is only for free or trial user
    if not current_user.should_upgrade():
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
