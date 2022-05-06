from app.onboarding.base import onboarding_bp
from flask import render_template


@onboarding_bp.route("/final", methods=["GET"])
def final():
    return render_template(
        "onboarding/final.html",
    )
