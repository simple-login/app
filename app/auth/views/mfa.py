import pyotp
from flask import request, render_template, redirect, url_for, flash, session
from flask_login import login_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.config import MFA_USER_ID
from app.log import LOG
from app.models import User


class OtpTokenForm(FlaskForm):
    token = StringField("Token", validators=[validators.DataRequired()])


@auth_bp.route("/mfa", methods=["GET", "POST"])
def mfa():
    # passed from login page
    user_id = session[MFA_USER_ID]
    user = User.get(user_id)

    if not user.enable_otp:
        raise Exception("Only user with MFA enabled should go to this page. %s", user)

    otp_token_form = OtpTokenForm()
    next_url = request.args.get("next")

    if otp_token_form.validate_on_submit():
        totp = pyotp.TOTP(user.otp_secret)

        if otp_token_form.validate_on_submit():
            token = otp_token_form.token.data

            if totp.verify(token):
                del session[MFA_USER_ID]

                login_user(user)
                flash(f"Welcome back {user.name}!")

                # User comes to login page from another page
                if next_url:
                    LOG.debug("redirect user to %s", next_url)
                    return redirect(next_url)
                else:
                    LOG.debug("redirect user to dashboard")
                    return redirect(url_for("dashboard.index"))

            else:
                flash("Incorrect token", "warning")

    return render_template("auth/mfa.html", otp_token_form=otp_token_form)
