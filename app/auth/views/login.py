from flask import request, render_template, redirect, url_for, flash
from flask_login import current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
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
    next_url = request.args.get("next")
    show_resend_activation = False

    if form.validate_on_submit():
        user = User.filter_by(email=form.email.data.strip().lower()).first()

        if not user:
            flash("Email or password incorrect", "error")
        elif not user.check_password(form.password.data):
            flash("Email or password incorrect", "error")
        elif not user.activated:
            show_resend_activation = True
            flash(
                "Please check your inbox for the activation email. You can also have this email re-sent",
                "error",
            )
        else:
            return after_login(user, next_url)

    return render_template(
        "auth/login.html",
        form=form,
        next_url=next_url,
        show_resend_activation=show_resend_activation,
    )
