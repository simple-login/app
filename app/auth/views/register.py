import arrow
from flask import request, flash, render_template, redirect, url_for
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import email_utils
from app.auth.base import auth_bp
from app.config import URL
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import User, ActivationCode
from app.utils import random_string, encode_url


class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])
    password = StringField(
        "Password", validators=[validators.DataRequired(), validators.Length(min=8)]
    )
    name = StringField("Name", validators=[validators.DataRequired()])


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        LOG.d("user is already authenticated, redirect to dashboard")
        return redirect(url_for("dashboard.index"))

    form = RegisterForm(request.form)
    next_url = request.args.get("next")

    if form.validate_on_submit():
        user = User.filter_by(email=form.email.data).first()

        if user:
            flash(f"Email {form.email.data} already exists", "warning")
        else:
            LOG.debug("create user %s", form.email.data)
            user = User.create(
                email=form.email.data, name=form.name.data, password=form.password.data
            )
            db.session.commit()

            send_activation_email(user, next_url)
            notify_admin(
                f"new user signs up {user.email}",
                f"{user.name} signs up at {arrow.now()}",
            )

            return render_template("auth/register_waiting_activation.html")

    return render_template("auth/register.html", form=form, next_url=next_url)


def send_activation_email(user, next_url):
    # the activation code is valid for 1h
    activation = ActivationCode.create(user_id=user.id, code=random_string(30))
    db.session.commit()

    # Send user activation email
    activation_link = f"{URL}/auth/activate?code={activation.code}"
    if next_url:
        LOG.d("redirect user to %s after activation", next_url)
        activation_link = activation_link + "&next=" + encode_url(next_url)

    email_utils.send(
        user.email,
        f"Welcome to SimpleLogin {user.name} - just one more step!",
        html_content=f"""
                Welcome to SimpleLogin! <br><br>

Our mission is to make the login process as smooth and as secure as possible. This should be easy. <br><br>

To get started, we need to confirm your email address, so please click this <a href="{activation_link}">link</a> 
to finish creating your account. Or you can paste this link into your browser: <br><br>

{activation_link} <br><br>

Your feedbacks are very important to us. Please feel free to reply to this email to let us know any 
of your suggestion! <br><br>

Thanks! <br><br>

SimpleLogin team.
            
            """,
    )
