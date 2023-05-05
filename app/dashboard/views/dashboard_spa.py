from flask import render_template
from flask_login import login_required

from app.dashboard.base import dashboard_bp


@dashboard_bp.route("/dashboard_spa", methods=["GET", "POST"])
@login_required
def dashboard_spa():
    return render_template(
        "dashboard/dashboard_spa.html"
    )
