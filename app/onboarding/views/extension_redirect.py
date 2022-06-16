from app.onboarding.base import onboarding_bp
from app.onboarding.utils import get_extension_info
from flask import redirect, url_for


@onboarding_bp.route("/extension_redirect", methods=["GET"])
def extension_redirect():
    info = get_extension_info()
    if not info:
        return redirect(url_for("dashboard.index"))
    return redirect(info.url)
