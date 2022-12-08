from flask import request, flash, render_template, redirect, url_for
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.auth.views.register import send_activation_email
from app.extensions import limiter
from app.log import LOG
from app.models import User
from app.utils import sanitize_email


class ResendActivationForm(FlaskForm):
    email = StringField("Email", validators=[validators.DataRequired()])


@auth_bp.route("/resend_activation", methods=["GET", "POST"])
@limiter.limit("10/hour")
def resend_activation():
    form = ResendActivationForm(request.form)

    if form.validate_on_submit():
        user = User.filter_by(email=sanitize_email(form.email.data)).first()

        if not user:
            flash("There is no such email", "warning")
            return render_template("auth/resend_activation.html", form=form)

        if user.activated:
            flash("Your account was already activated, please login", "success")
            return redirect(url_for("auth.login"))

        # user is not activated
        LOG.d("user %s is not activated", user)
        flash(
            "An activation email has been sent to you. Please check your inbox/spam folder.",
            "warning",
        )
        send_activation_email(user, request.args.get("next"))
        return render_template("auth/register_waiting_activation.html")

    return render_template("auth/resend_activation.html", form=form)
