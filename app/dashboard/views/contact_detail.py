from typing import Optional

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.alias_audit_log_utils import emit_alias_audit_log, AliasAuditLogAction
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.models import Contact
from app.pgp_utils import PGPException, load_public_key_and_check, create_pgp_context


class PGPContactForm(FlaskForm):
    action = StringField(
        "action",
        validators=[validators.DataRequired(), validators.AnyOf(("save", "remove"))],
    )
    pgp = StringField("pgp", validators=[validators.Optional()])


@dashboard_bp.route("/contact/<int:contact_id>/", methods=["GET", "POST"])
@login_required
def contact_detail_route(contact_id):
    contact: Optional[Contact] = Contact.get(contact_id)
    if not contact or contact.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    alias = contact.alias
    pgp_form = PGPContactForm()

    if request.method == "POST":
        if request.form.get("form-name") == "pgp":
            if not pgp_form.validate():
                flash("Invalid request", "warning")
                return redirect(request.url)
            if pgp_form.action.data == "save":
                if not current_user.is_premium():
                    flash("Only premium plan can add PGP Key", "warning")
                    return redirect(
                        url_for("dashboard.contact_detail_route", contact_id=contact_id)
                    )
                if not pgp_form.pgp.data:
                    flash("Invalid pgp key")
                else:
                    contact.pgp_public_key = pgp_form.pgp.data
                    try:
                        contact.pgp_finger_print = load_public_key_and_check(
                            contact.pgp_public_key, create_pgp_context()
                        )
                    except PGPException:
                        flash("Cannot add the public key, please verify it", "error")
                    else:
                        emit_alias_audit_log(
                            alias=alias,
                            action=AliasAuditLogAction.UpdateContact,
                            message=f"Added PGP key {contact.pgp_public_key} for contact {contact_id} ({contact.email})",
                        )
                        Session.commit()
                        flash(
                            f"PGP public key for {contact.email} is saved successfully",
                            "success",
                        )
                        return redirect(
                            url_for(
                                "dashboard.contact_detail_route", contact_id=contact_id
                            )
                        )
            elif pgp_form.action.data == "remove":
                # Free user can decide to remove contact PGP key
                emit_alias_audit_log(
                    alias=alias,
                    action=AliasAuditLogAction.UpdateContact,
                    message=f"Removed PGP key {contact.pgp_public_key} for contact {contact_id} ({contact.email})",
                )
                contact.pgp_public_key = None
                contact.pgp_finger_print = None
                Session.commit()
                flash(f"PGP public key for {contact.email} is removed", "success")
                return redirect(
                    url_for("dashboard.contact_detail_route", contact_id=contact_id)
                )

    return render_template(
        "dashboard/contact_detail.html", contact=contact, alias=alias, pgp_form=pgp_form
    )
