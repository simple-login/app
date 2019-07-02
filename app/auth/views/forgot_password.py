from flask import request, render_template, redirect, url_for
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.dashboard.views.setting import send_reset_password_email
from app.models import User


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])


@auth_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm(request.form)

    if form.validate_on_submit():
        email = form.email.data

        user = User.get_by(email=email)

        if not user:
            error = "No such user, are you sure the email is correct?"
            return render_template("auth/forgot_password.html", form=form, error=error)

        send_reset_password_email(user)
        return redirect(url_for("auth.forgot_password"))

    return render_template("auth/forgot_password.html", form=form)
