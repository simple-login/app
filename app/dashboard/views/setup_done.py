import arrow
from flask import render_template, make_response
from flask_login import login_required

from app.config import URL
from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/setup_done", methods=["GET", "POST"])
@login_required
def setup_done():
    response = make_response(render_template("dashboard/setup_done.html"))

    response.set_cookie(
        "setup_done",
        value="true",
        expires=arrow.now().shift(days=30).datetime,
        secure=True if URL.startswith("https") else False,
        httponly=True,
        samesite="Lax",
    )

    return response
