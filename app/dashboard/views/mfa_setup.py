import pyotp
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.log import LOG
from app.models import RecoveryCode


class OtpTokenForm(FlaskForm):
    token = StringField("Token", validators=[validators.DataRequired()])


@dashboard_bp.route("/mfa_setup", methods=["GET", "POST"])
@login_required
@sudo_required
def mfa_setup():
    if current_user.enable_otp:
        flash("you have already enabled MFA", "warning")
        return redirect(url_for("dashboard.index"))

    otp_token_form = OtpTokenForm()

    if not current_user.otp_secret:
        LOG.d("Generate otp_secret for user %s", current_user)
        current_user.otp_secret = pyotp.random_base32()
        Session.commit()

    totp = pyotp.TOTP(current_user.otp_secret)

    if otp_token_form.validate_on_submit():
        token = otp_token_form.token.data.replace(" ", "")

        if totp.verify(token) and current_user.last_otp != token:
            current_user.enable_otp = True
            current_user.last_otp = token
            Session.commit()
            flash("MFA has been activated", "success")
            recovery_codes = RecoveryCode.generate(current_user)
            return render_template(
                "dashboard/recovery_code.html", recovery_codes=recovery_codes
            )
        else:
            flash("Incorrect token", "warning")

    otp_uri = pyotp.totp.TOTP(current_user.otp_secret).provisioning_uri(
        name=current_user.email, issuer_name="SimpleLogin"
    )

    return render_template(
        "dashboard/mfa_setup.html", otp_token_form=otp_token_form, otp_uri=otp_uri
    )
