from flask import request, render_template, redirect, url_for
from flask_login import login_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.log import LOG
from app.models import User


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])
    password = StringField("Password", validators=[validators.DataRequired()])


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        LOG.d("user is already authenticated, redirect to dashboard")
        return redirect(url_for("dashboard.index"))

    form = LoginForm(request.form)

    if form.validate_on_submit():
        user = User.filter_by(email=form.email.data).first()

        if not user:
            return render_template(
                "auth/login.html", form=form, error="Email not exist in our system"
            )

        if not user.check_password(form.password.data):
            return render_template("auth/login.html", form=form, error="Wrong password")

        if not user.activated:
            return render_template(
                "auth/login.html",
                form=form,
                show_resend_activation=True,
                error="Please check your inbox for the activation email. You can also have this email re-sent",
            )

        LOG.debug("log user %s in", user)
        login_user(user)

        # User comes to login page from another page
        if "next" in request.args:
            next_url = request.args.get("next")
            LOG.debug("redirect user to %s", next_url)
            return redirect(next_url)
        else:
            LOG.debug("redirect user to dashboard")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", form=form)
