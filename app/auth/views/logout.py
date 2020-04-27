from flask import redirect, url_for, flash
from flask_login import logout_user

from app.auth.base import auth_bp


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("You are logged out", "success")
    return redirect(url_for("auth.login"))
