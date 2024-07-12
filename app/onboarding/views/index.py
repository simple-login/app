from app.onboarding.base import onboarding_bp
from flask import render_template, url_for, redirect


@onboarding_bp.route("/", methods=["GET"])
def index():
    # Do the redirect to ensure cookies are set because they are SameSite=lax/strict
    return redirect(url_for("onboarding.setup"))


@onboarding_bp.route("/setup", methods=["GET"])
def setup():
    return render_template("onboarding/setup.html")
