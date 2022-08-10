import arrow
from flask import redirect, url_for, request, flash
from flask_login import current_user, login_user

from app.auth.base import auth_bp
from app.log import LOG
from app.models import ApiToCookieToken
from app.utils import sanitize_next_url


@auth_bp.route("/api_to_cookie", methods=["GET"])
def api_to_cookie():
    if current_user.is_authenticated:
        LOG.d("user is already authenticated, redirect to dashboard")
        return redirect(url_for("dashboard.index"))
    code = request.args.get("token")
    if not code:
        flash("Missing token", "error")
        return redirect(url_for("auth.login"))

    token = ApiToCookieToken.get_by(code=code)
    if not token or token.created_at < arrow.now().shift(minutes=-5):
        flash("Missing token", "error")
        return redirect(url_for("auth.login"))

    login_user(token.user)
    ApiToCookieToken.delete(token.id, commit=True)

    next_url = sanitize_next_url(request.args.get("next"))
    if next_url:
        return redirect(next_url)
    else:
        return redirect(url_for("dashboard.index"))
