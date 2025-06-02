from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app.config import PADDLE_MONTHLY_PRODUCT_ID, PADDLE_YEARLY_PRODUCT_ID
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.models import Subscription, PlanEnum
from app.paddle_utils import cancel_subscription, change_plan


@dashboard_bp.route("/billing", methods=["GET", "POST"])
@login_required
def billing():
    # sanity check: make sure this page is only for user who has paddle subscription
    sub: Subscription = current_user.get_paddle_subscription()

    if not sub:
        flash("You don't have any active subscription", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if request.form.get("form-name") == "cancel":
            LOG.w(f"User {current_user} cancels their subscription")
            success = cancel_subscription(sub.subscription_id)

            if success:
                sub.cancelled = True
                Session.commit()
                flash("Your subscription has been canceled successfully", "success")
            else:
                flash(
                    "Something went wrong, sorry for the inconvenience. Please retry. "
                    "We are already notified and will be on it asap",
                    "error",
                )

            return redirect(url_for("dashboard.billing"))
        elif request.form.get("form-name") == "change-monthly":
            LOG.d(f"User {current_user} changes to monthly plan")
            success, msg = change_plan(
                current_user, sub.subscription_id, PADDLE_MONTHLY_PRODUCT_ID
            )

            if success:
                sub.plan = PlanEnum.monthly
                Session.commit()
                flash("Your subscription has been updated", "success")
            else:
                if msg:
                    flash(msg, "error")
                else:
                    flash(
                        "Something went wrong, sorry for the inconvenience. Please retry. "
                        "We are already notified and will be on it asap",
                        "error",
                    )

            return redirect(url_for("dashboard.billing"))
        elif request.form.get("form-name") == "change-yearly":
            LOG.d(f"User {current_user} changes to yearly plan")
            success, msg = change_plan(
                current_user, sub.subscription_id, PADDLE_YEARLY_PRODUCT_ID
            )

            if success:
                sub.plan = PlanEnum.yearly
                Session.commit()
                flash("Your subscription has been updated", "success")
            else:
                if msg:
                    flash(msg, "error")
                else:
                    flash(
                        "Something went wrong, sorry for the inconvenience. Please retry. "
                        "We are already notified and will be on it asap",
                        "error",
                    )

            return redirect(url_for("dashboard.billing"))

    return render_template("dashboard/billing.html", sub=sub, PlanEnum=PlanEnum)
