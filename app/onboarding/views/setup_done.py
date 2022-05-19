import arrow
from flask import make_response, render_template
from flask_login import login_required

from app.config import URL
from app.onboarding.base import onboarding_bp


@onboarding_bp.route("/setup_done", methods=["GET", "POST"])
@login_required
def setup_done():
    response = make_response(render_template("onboarding/setup_done.html"))

    # TODO: Remove when the extension is updated everywhere
    response.set_cookie(
        "setup_done",
        value="true",
        expires=arrow.now().shift(days=30).datetime,
        secure=True if URL.startswith("https") else False,
        httponly=True,
        samesite="Lax",
    )

    return response
