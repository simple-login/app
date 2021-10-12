from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.dashboard.base import dashboard_bp
from app.db import Session
from app.models import Contact
from app.pgp_utils import PGPException, load_public_key_and_check


@dashboard_bp.route("/contact/<int:contact_id>/", methods=["GET", "POST"])
@login_required
def contact_detail_route(contact_id):
    contact = Contact.get(contact_id)
    if not contact or contact.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    alias = contact.alias

    if request.method == "POST":
        if request.form.get("form-name") == "pgp":
            if request.form.get("action") == "save":
                if not current_user.is_premium():
                    flash("Only premium plan can add PGP Key", "warning")
                    return redirect(
                        url_for("dashboard.contact_detail_route", contact_id=contact_id)
                    )

                contact.pgp_public_key = request.form.get("pgp")
                try:
                    contact.pgp_finger_print = load_public_key_and_check(
                        contact.pgp_public_key
                    )
                except PGPException:
                    flash("Cannot add the public key, please verify it", "error")
                else:
                    Session.commit()
                    flash(
                        f"PGP public key for {contact.email} is saved successfully",
                        "success",
                    )
                    return redirect(
                        url_for("dashboard.contact_detail_route", contact_id=contact_id)
                    )
            elif request.form.get("action") == "remove":
                # Free user can decide to remove contact PGP key
                contact.pgp_public_key = None
                contact.pgp_finger_print = None
                Session.commit()
                flash(f"PGP public key for {contact.email} is removed", "success")
                return redirect(
                    url_for("dashboard.contact_detail_route", contact_id=contact_id)
                )

    return render_template(
        "dashboard/contact_detail.html", contact=contact, alias=alias
    )
