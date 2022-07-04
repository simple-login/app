import arrow
from app.config import CONNECT_WITH_PROTON_COOKIE_NAME, URL
from flask import make_response, redirect, url_for, flash
from flask_login import current_user
from .base import internal_bp


@internal_bp.route("/integrations/proton")
def set_enable_proton_cookie():
    if current_user.is_authenticated:
        redirect_url = url_for("dashboard.setting", _anchor="connect-with-proton")
    else:
        redirect_url = url_for("auth.login")

    response = make_response(redirect(redirect_url))
    if CONNECT_WITH_PROTON_COOKIE_NAME:
        flash("You can now connect your Proton and your SimpleLogin account", "success")
        response.set_cookie(
            CONNECT_WITH_PROTON_COOKIE_NAME,
            value="true",
            expires=arrow.now().shift(days=30).datetime,
            secure=True if URL.startswith("https") else False,
            httponly=True,
            samesite="Lax",
        )
    return response
