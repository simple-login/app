from app.db import Session

"""
List of sent and forwarded emails
"""

from flask import render_template, request, flash, redirect
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.dashboard.base import dashboard_bp
from app.models import (
    EmailLog,
)


@dashboard_bp.route("/email_log", methods=["GET"])
@login_required
def email_log():
    email_log = (
        EmailLog.filter_by(user_id=current_user.id)
        .order_by(EmailLog.created_at.desc())
        .all()
    )

    return render_template(
        "dashboard/email_log.html",
        email_log=email_log,
    )
