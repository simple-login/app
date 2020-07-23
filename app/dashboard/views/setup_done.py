from flask import render_template
from flask_login import login_required

from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/setup_done", methods=["GET", "POST"])
@login_required
def setup_done():
    return render_template("dashboard/setup_done.html")
