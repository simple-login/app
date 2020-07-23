from flask import redirect, url_for, flash, make_response
from flask_login import logout_user

from app.auth.base import auth_bp
from app.config import SESSION_COOKIE_NAME


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("You are logged out", "success")
    response = make_response(redirect(url_for("auth.login")))
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie("mfa")
    response.delete_cookie("dark-mode")

    return response
