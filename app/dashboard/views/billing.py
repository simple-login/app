from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.log import LOG
from app.models import Subscription
from app.extensions import db
from app.paddle_utils import cancel_subscription


@dashboard_bp.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    # sanity check: make sure this page is only for user who has paddle subscription
    sub: Subscription = current_user.get_subscription()

    if not sub:
        flash("You don't have any active subscription", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if request.form.get("form-name") == "cancel":
            LOG.warning(f"User {current_user} cancels their subscription")
            success = cancel_subscription(sub.subscription_id)

            if success:
                sub.cancelled = True
                db.session.commit()
                flash("Your subscription has been canceled successfully", "success")
            else:
                flash(
                    "Something went wrong, sorry for the inconvenience. Please retry. We are already notified and will be on it asap",
                    "error",
                )

            return redirect(url_for("dashboard.billing"))

    return render_template("dashboard/billing.html", sub=sub)
