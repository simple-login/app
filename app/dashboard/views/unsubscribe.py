"""
Allow user to "unsubscribe", aka block an email alias
"""

from flask import redirect, url_for, flash, request, render_template
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.models import Alias


@dashboard_bp.route("/unsubscribe/<alias_id>", methods=["GET", "POST"])
@login_required
def unsubscribe(alias_id):
    alias = Alias.get(alias_id)
    if not alias:
        flash("Incorrect link. Redirect you to the home page", "warning")
        return redirect(url_for("dashboard.index"))

    if alias.user_id != current_user.id:
        flash(
            "You don't have access to this page. Redirect you to the home page",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    # automatic unsubscribe, according to https://tools.ietf.org/html/rfc8058
    if request.method == "POST":
        alias.enabled = False
        flash(f"Alias {alias.email} has been blocked", "success")
        db.session.commit()

        return redirect(url_for("dashboard.index", highlight_alias_id=alias.id))
    else:  # ask user confirmation
        return render_template("dashboard/unsubscribe.html", alias=alias.email)
