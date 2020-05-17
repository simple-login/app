from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, validators

from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.models import RecoveryCode


class LoginForm(FlaskForm):
    password = PasswordField("Password", validators=[validators.DataRequired()])


@dashboard_bp.route("/fido_cancel", methods=["GET", "POST"])
@login_required
def fido_cancel():
    if not current_user.fido_enabled():
        flash("You haven't registed a security key", "warning")
        return redirect(url_for("dashboard.index"))

    password_check_form = LoginForm()

    if password_check_form.validate_on_submit():
        password = password_check_form.password.data

        if current_user.check_password(password):
            current_user.fido_pk = None
            current_user.fido_uuid = None
            current_user.fido_sign_count = None
            current_user.fido_credential_id = None
            db.session.commit()

            # user does not have any 2FA enabled left, delete all recovery codes
            if not current_user.two_factor_authentication_enabled():
                RecoveryCode.empty(current_user)

            flash("We've unlinked your security key.", "success")
            return redirect(url_for("dashboard.index"))
        else:
            flash("Incorrect password", "warning")

    return render_template(
        "dashboard/fido_cancel.html", password_check_form=password_check_form
    )
