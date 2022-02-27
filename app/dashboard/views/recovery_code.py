from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.log import LOG
from app.models import RecoveryCode


@dashboard_bp.route("/recovery_code", methods=["GET", "POST"])
@login_required
def recovery_code_route():
    if not current_user.two_factor_authentication_enabled():
        flash("you need to enable either TOTP or WebAuthn", "warning")
        return redirect(url_for("dashboard.index"))

    recovery_codes = RecoveryCode.filter_by(user_id=current_user.id).all()
    if request.method == "GET" and not recovery_codes:
        # user arrives at this page for the first time
        LOG.d("%s has no recovery keys, generate", current_user)
        RecoveryCode.generate(current_user)
        recovery_codes = RecoveryCode.filter_by(user_id=current_user.id).all()

    if request.method == "POST":
        RecoveryCode.generate(current_user)
        flash("New recovery codes generated", "success")
        return redirect(url_for("dashboard.recovery_code_route"))

    return render_template(
        "dashboard/recovery_code.html", recovery_codes=recovery_codes
    )
