from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    # sanity check: make sure this page is only for user who has paddle subscription
    sub = current_user.get_subscription()

    if not sub:
        flash("You don't have any active subscription", "warning")
        return redirect(url_for("dashboard.index"))

    return render_template("dashboard/billing.html", sub=sub)
