import requests
from flask import request, flash, render_template, redirect, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import email_utils, config
from app.auth.base import auth_bp
from app.auth.views.login_utils import get_referral
from app.config import URL, HCAPTCHA_SECRET, HCAPTCHA_SITEKEY
from app.email_utils import (
    email_can_be_used_as_mailbox,
    personal_email_already_used,
)
from app.extensions import db
from app.log import LOG
from app.models import User, ActivationCode
from app.utils import random_string, encode_url, sanitize_email


class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])
    password = StringField(
        "Password", validators=[validators.DataRequired(), validators.Length(min=8)]
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        LOG.d("user is already authenticated, redirect to dashboard")
        flash("You are already logged in", "warning")
        return redirect(url_for("dashboard.index"))

    if config.DISABLE_REGISTRATION:
        flash("Registration is closed", "error")
        return redirect(url_for("auth.login"))

    form = RegisterForm(request.form)
    next_url = request.args.get("next")

    if form.validate_on_submit():
        # only check if hcaptcha is enabled
        if HCAPTCHA_SECRET:
            # check with hCaptcha
            token = request.form.get("h-captcha-response")
            params = {"secret": HCAPTCHA_SECRET, "response": token}
            hcaptcha_res = requests.post(
                "https://hcaptcha.com/siteverify", data=params
            ).json()
            # return something like
            # {'success': True,
            #  'challenge_ts': '2020-07-23T10:03:25',
            #  'hostname': '127.0.0.1'}
            if not hcaptcha_res["success"]:
                LOG.warning(
                    "User put wrong captcha %s %s",
                    form.email.data,
                    hcaptcha_res,
                )
                flash("Wrong Captcha", "error")
                return render_template(
                    "auth/register.html",
                    form=form,
                    next_url=next_url,
                    HCAPTCHA_SITEKEY=HCAPTCHA_SITEKEY,
                )

        email = sanitize_email(form.email.data)
        if not email_can_be_used_as_mailbox(email):
            flash("You cannot use this email address as your personal inbox.", "error")

        else:
            if personal_email_already_used(email):
                flash(f"Email {email} already used", "error")
            else:
                LOG.debug("create user %s", email)
                user = User.create(
                    email=email,
                    name="",
                    password=form.password.data,
                    referral=get_referral(),
                )
                db.session.commit()

                try:
                    send_activation_email(user, next_url)
                except Exception:
                    flash("Invalid email, are you sure the email is correct?", "error")
                    return redirect(url_for("auth.register"))

                return render_template("auth/register_waiting_activation.html")

    return render_template(
        "auth/register.html",
        form=form,
        next_url=next_url,
        HCAPTCHA_SITEKEY=HCAPTCHA_SITEKEY,
    )


def send_activation_email(user, next_url):
    # the activation code is valid for 1h
    activation = ActivationCode.create(user_id=user.id, code=random_string(30))
    db.session.commit()

    # Send user activation email
    activation_link = f"{URL}/auth/activate?code={activation.code}"
    if next_url:
        LOG.d("redirect user to %s after activation", next_url)
        activation_link = activation_link + "&next=" + encode_url(next_url)

    email_utils.send_activation_email(user.email, activation_link)
