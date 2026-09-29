import arrow
from flask import redirect, url_for, request, flash
from flask_login import current_user, login_user

from app.auth.base import auth_bp
from app.models import ApiToCookieToken
from app.session import clear_session_sudo_mode
from app.utils import sanitize_next_url


@auth_bp.route("/api_to_cookie", methods=["GET"])
def api_to_cookie():
    code = request.args.get("token")
    if not code:
        flash("Missing token", "error")
        return redirect(url_for("auth.login"))

    if current_user and current_user.is_authenticated:
        token = ApiToCookieToken.get_by(code=code, user_id=current_user.id)
    else:
        token = ApiToCookieToken.get_by(code=code)

    if not token or token.created_at < arrow.now().shift(minutes=-5):
        flash("Missing token", "error")
        return redirect(url_for("auth.login"))

    user = token.user
    ApiToCookieToken.delete(token.id, commit=True)
    # An api key is not a password, the session it creates must not be in sudo
    # mode, not even if the previous session of this browser was
    clear_session_sudo_mode()
    login_user(user)

    next_url = sanitize_next_url(request.args.get("next"))
    if next_url:
        return redirect(next_url)

    return redirect(url_for("dashboard.index"))
