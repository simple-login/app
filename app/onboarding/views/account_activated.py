from app.onboarding.base import onboarding_bp
from app.onboarding.utils import get_extension_info
from flask import redirect, render_template, url_for
from flask_login import login_required


@onboarding_bp.route("/account_activated", methods=["GET"])
@login_required
def account_activated():
    info = get_extension_info()
    if not info:
        return redirect(url_for("dashboard.index"))

    return render_template(
        "onboarding/account_activated.html",
        extension_link=info.url,
        browser_name=info.browser,
    )
