from app.onboarding.base import onboarding_bp
from flask import render_template


@onboarding_bp.route("/", methods=["GET"])
def index():
    return render_template("onboarding/index.html")
