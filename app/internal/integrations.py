import arrow
from flask import make_response, redirect, url_for, flash
from flask_login import current_user
from .base import internal_bp
from app import config


@internal_bp.route("/integrations/proton")
def set_enable_proton_cookie():
    if current_user.is_authenticated:
        redirect_url = url_for("dashboard.setting", _anchor="connect-with-proton")
    else:
        redirect_url = url_for("auth.login")

    response = make_response(redirect(redirect_url))
    if config.PROTON_ALLOW_INTERNAL_LINK:
        flash("You can now connect your Proton and your SimpleLogin account", "success")
        response.set_cookie(
            config.CONNECT_WITH_PROTON_COOKIE_NAME,
            value="true",
            expires=arrow.now().shift(days=30).datetime,
            secure=True if config.URL.startswith("https") else False,
            httponly=True,
            samesite="Lax",
        )
    return response
