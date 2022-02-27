from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.models import RecoveryCode


@dashboard_bp.route("/mfa_cancel", methods=["GET", "POST"])
@login_required
@sudo_required
def mfa_cancel():
    if not current_user.enable_otp:
        flash("you don't have MFA enabled", "warning")
        return redirect(url_for("dashboard.index"))

    # user cancels TOTP
    if request.method == "POST":
        current_user.enable_otp = False
        current_user.otp_secret = None
        Session.commit()

        # user does not have any 2FA enabled left, delete all recovery codes
        if not current_user.two_factor_authentication_enabled():
            RecoveryCode.empty(current_user)

        flash("TOTP is now disabled", "warning")
        return redirect(url_for("dashboard.index"))

    return render_template("dashboard/mfa_cancel.html")
