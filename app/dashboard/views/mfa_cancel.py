import pyotp
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.models import RecoveryCode
from app.dashboard.views.enter_sudo import sudo_required


class OtpTokenForm(FlaskForm):
    token = StringField("Token", validators=[validators.DataRequired()])


@dashboard_bp.route("/mfa_cancel", methods=["GET", "POST"])
@login_required
@sudo_required
def mfa_cancel():
    if not current_user.enable_otp:
        flash("you don't have MFA enabled", "warning")
        return redirect(url_for("dashboard.index"))

    otp_token_form = OtpTokenForm()
    totp = pyotp.TOTP(current_user.otp_secret)

    if otp_token_form.validate_on_submit():
        token = otp_token_form.token.data

        if totp.verify(token):
            current_user.enable_otp = False
            current_user.otp_secret = None
            db.session.commit()

            # user does not have any 2FA enabled left, delete all recovery codes
            if not current_user.two_factor_authentication_enabled():
                RecoveryCode.empty(current_user)

            flash("MFA is now disabled", "warning")
            return redirect(url_for("dashboard.index"))
        else:
            flash("Incorrect token", "warning")

    return render_template("dashboard/mfa_cancel.html", otp_token_form=otp_token_form)
