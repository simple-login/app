"""
Allow user to "unsubscribe", aka block an email alias
"""

from flask import redirect, url_for, flash
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.email_utils import notify_admin
from app.extensions import db
from app.models import GenEmail


@dashboard_bp.route("/unsubscribe/<gen_email_id>", methods=["GET"])
@login_required
def unsubscribe(gen_email_id):
    gen_email = GenEmail.get(gen_email_id)
    if not gen_email:
        flash("Incorrect link. Redirect you to the home page", "warning")
        return redirect(url_for("dashboard.index"))

    if gen_email.user_id != current_user.id:
        flash(
            "You don't have access to this page. Redirect you to the home page",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    gen_email.enabled = False
    flash(f"Alias {gen_email.email} has been blocked", "success")
    db.session.commit()

    notify_admin(f"User {current_user.email} has unsubscribed an alias")
    return redirect(url_for("dashboard.index"))
