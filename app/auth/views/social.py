from flask import render_template, redirect, url_for
from flask_login import current_user

from app.auth.base import auth_bp
from app.log import LOG


@auth_bp.route("/social", methods=["GET", "POST"])
def social():
    if current_user.is_authenticated:
        LOG.d("user is already authenticated, redirect to dashboard")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/social.html")
