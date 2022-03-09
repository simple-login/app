from flask import redirect, url_for, flash, render_template, request
from flask_login import login_required, current_user

from app.config import PAGE_LIMIT
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

    if not notification.read:
        notification.read = True
        Session.commit()

    if request.method == "POST":
        notification_title = notification.title or notification.message[:20]
        Notification.delete(notification_id)
        Session.commit()
        flash(f"{notification_title} has been deleted", "success")

        return redirect(url_for("dashboard.index"))
    else:
        return render_template("dashboard/notification.html", notification=notification)


@dashboard_bp.route("/notifications", methods=["GET", "POST"])
@login_required
def notifications_route():
    page = 0
    if request.args.get("page"):
        page = int(request.args.get("page"))

    notifications = (
        Notification.filter_by(user_id=current_user.id)
        .order_by(Notification.read, Notification.created_at.desc())
        .limit(PAGE_LIMIT + 1)  # load a record more to know whether there's more
        .offset(page * PAGE_LIMIT)
        .all()
    )

    return render_template(
        "dashboard/notifications.html",
        notifications=notifications,
        page=page,
        last_page=len(notifications) <= PAGE_LIMIT,
    )
