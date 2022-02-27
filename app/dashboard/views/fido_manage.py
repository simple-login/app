from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import HiddenField, validators

from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.log import LOG
from app.models import RecoveryCode, Fido


class FidoManageForm(FlaskForm):
    credential_id = HiddenField("credential_id", validators=[validators.DataRequired()])


@dashboard_bp.route("/fido_manage", methods=["GET", "POST"])
@login_required
@sudo_required
def fido_manage():
    if not current_user.fido_enabled():
        flash("You haven't registered a security key", "warning")
        return redirect(url_for("dashboard.index"))

    fido_manage_form = FidoManageForm()

    if fido_manage_form.validate_on_submit():
        credential_id = fido_manage_form.credential_id.data

        fido_key = Fido.get_by(uuid=current_user.fido_uuid, credential_id=credential_id)

        if not fido_key:
            flash("Unknown error, redirect back to manage page", "warning")
            return redirect(url_for("dashboard.fido_manage"))

        Fido.delete(fido_key.id)
        Session.commit()

        LOG.d(f"FIDO Key ID={fido_key.id} Removed")
        flash(f"Key {fido_key.name} successfully unlinked", "success")

        # Disable FIDO for the user if all keys have been deleted
        if not Fido.filter_by(uuid=current_user.fido_uuid).all():
            current_user.fido_uuid = None
            Session.commit()

            # user does not have any 2FA enabled left, delete all recovery codes
            if not current_user.two_factor_authentication_enabled():
                RecoveryCode.empty(current_user)

            return redirect(url_for("dashboard.index"))

        return redirect(url_for("dashboard.fido_manage"))

    return render_template(
        "dashboard/fido_manage.html",
        fido_manage_form=fido_manage_form,
        keys=Fido.filter_by(uuid=current_user.fido_uuid),
    )
