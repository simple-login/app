from app.onboarding.base import onboarding_bp
from flask import render_template
from flask_login import current_user


@onboarding_bp.route("/", methods=["GET"])
def index():
    return render_template(
        "onboarding/index.html", is_user_logged_in=current_user is not None
    )
