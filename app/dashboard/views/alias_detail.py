from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app import alias_utils
from app.api.serializer import get_alias_info_v3
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.utils import CSRFValidationForm


@dashboard_bp.route("/aliases/<int:alias_id>", methods=["GET", "POST"])
@login_required
def aliases(alias_id):
    alias_info = get_alias_info_v3(current_user, alias_id)

    # sanity check
    if not alias_info:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    alias = alias_info.alias

    if alias.user_id != current_user.id:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    mailboxes = current_user.mailboxes()

    csrf_form = CSRFValidationForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") in ("delete-alias", "disable-alias"):
            if not alias or alias.user_id != current_user.id:
                flash("Unknown error, sorry for the inconvenience", "error")
                return redirect(url_for("dashboard.index"))

            if request.form.get("form-name") == "delete-alias":
                LOG.d("delete alias %s", alias)
                email = alias.email
                alias_utils.delete_alias(alias, current_user)
                flash(f"Alias {email} has been deleted", "success")
                return redirect(url_for("dashboard.index"))

            elif request.form.get("form-name") == "disable-alias":
                alias.enabled = False
                Session.commit()
                flash(f"Alias {alias.email} has been disabled", "success")

        return redirect(url_for("dashboard.aliases", alias_id=alias.id))

    return render_template(
        "dashboard/alias_detail.html",
        alias_info=alias_info,
        mailboxes=mailboxes,
        csrf_form=csrf_form,
    )
