from flask import redirect, url_for, flash, make_response

from app.auth.base import auth_bp
from app.config import SESSION_COOKIE_NAME
from app.session import logout_session


@auth_bp.route("/logout")
def logout():
    logout_session()
    flash("You are logged out", "success")
    response = make_response(redirect(url_for("auth.login")))
    response.delete_cookie(SESSION_COOKIE_NAME)
    response.delete_cookie("mfa")
    response.delete_cookie("dark-mode")

    return response
