import uuid

from flask import request, flash, render_template, url_for, g
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
from app.db import Session
from app.extensions import limiter
from app.models import ResetPasswordCode
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


class ResetPasswordForm(FlaskForm):
    password = StringField(
        "Password",
        validators=[validators.DataRequired(), validators.Length(min=8, max=100)],
    )


@auth_bp.route("/reset_password", methods=["GET", "POST"])
@limiter.limit(
    "10/minute", deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit
)
def reset_password():
    form = ResetPasswordForm(request.form)

    reset_password_code_str = request.args.get("code")

    reset_password_code: ResetPasswordCode = ResetPasswordCode.get_by(
        code=reset_password_code_str
    )

    if not reset_password_code:
        # Trigger rate limiter
        g.deduct_limit = True
        error = (
            "The reset password link can be used only once. "
            "Please request a new link to reset password."
        )
        return render_template("auth/reset_password.html", form=form, error=error)

    if reset_password_code.is_expired():
        error = "The link has been already expired. Please make a new request of the reset password link"
        return render_template("auth/reset_password.html", form=form, error=error)

    if form.validate_on_submit():
        user = reset_password_code.user
        new_password = form.password.data

        # avoid user reusing the old password
        if user.check_password(new_password):
            error = "You cannot reuse the same password"
            return render_template("auth/reset_password.html", form=form, error=error)

        user.set_password(new_password)

        flash("Your new password has been set", "success")

        # this can be served to activate user too
        user.activated = True
        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.ResetPassword,
            message="User has reset their password",
        )

        # remove all reset password codes
        ResetPasswordCode.filter_by(user_id=user.id).delete()

        # change the alternative_id to log user out on other browsers
        user.alternative_id = str(uuid.uuid4())

        Session.commit()

        # do not use login_user(user) here
        # to make sure user needs to go through MFA if enabled
        return after_login(user, url_for("dashboard.index"))

    return render_template("auth/reset_password.html", form=form)
