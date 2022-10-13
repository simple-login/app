from flask import request, render_template, redirect, url_for, flash, g
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.dashboard.views.setting import send_reset_password_email
from app.extensions import limiter
from app.log import LOG
from app.models import User
from app.utils import sanitize_email


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])


@auth_bp.route("/forgot_password", methods=["GET", "POST"])
@limiter.limit(
    "10/minute", deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit
)
def forgot_password():
    form = ForgotPasswordForm(request.form)

    if form.validate_on_submit():
        # Trigger rate limiter
        g.deduct_limit = True

        email = sanitize_email(form.email.data)
        flash(
            "If your email is correct, you are going to receive an email to reset your password",
            "success",
        )
        user = User.get_by(email=email)

        if user:
            LOG.d("Send forgot password email to %s", user)
            send_reset_password_email(user)
            return redirect(url_for("auth.forgot_password"))

    return render_template("auth/forgot_password.html", form=form)
