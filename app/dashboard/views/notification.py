from flask import redirect, url_for, flash, render_template, request
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.db import Session
from app.models import Notification


@dashboard_bp.route("/notification/<notification_id>", methods=["GET", "POST"])
@login_required
def notification_route(notification_id):
    notification = Notification.get(notification_id)

    if not notification:
        flash("Incorrect link. Redirect you to the home page", "warning")
        return redirect(url_for("dashboard.index"))

    if notification.user_id != current_user.id:
        flash(
            "You don't have access to this page. Redirect you to the home page",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        notification_title = notification.title or notification.message[:20]
        Notification.delete(notification_id)
        Session.commit()
        flash(f"{notification_title} has been deleted", "success")

        return redirect(url_for("dashboard.index"))
    else:
        return render_template("dashboard/notification.html", notification=notification)
