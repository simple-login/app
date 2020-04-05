import re
from email.utils import parseaddr

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators, ValidationError

from app.config import EMAIL_DOMAIN
from app.dashboard.base import dashboard_bp
from app.email_utils import parseaddr_unicode
from app.extensions import db
from app.log import LOG
from app.models import Alias, Contact
from app.utils import random_string


def email_validator():
    """validate email address. Handle both only email and email with name:
    - ab@cd.com
    - AB CD <ab@cd.com>

    """
    message = "Invalid email format. Email must be either email@example.com or *First Last <email@example.com>*"

    def _check(form, field):
        email = field.data
        email = email.strip()
        email_part = email

        if "<" in email and ">" in email:
            if email.find("<") + 1 < email.find(">"):
                email_part = email[email.find("<") + 1 : email.find(">")].strip()

        if re.match(r"^[A-Za-z0-9\.\+_-]+@[A-Za-z0-9\._-]+\.[a-zA-Z]*$", email_part):
            return

        raise ValidationError(message)

    return _check


class NewContactForm(FlaskForm):
    email = StringField(
        "Email", validators=[validators.DataRequired(), email_validator()]
    )


@dashboard_bp.route("/alias_contact_manager/<alias_id>/", methods=["GET", "POST"])
@login_required
def alias_contact_manager(alias_id):
    highlight_contact_id = None
    if request.args.get("highlight_contact_id"):
        highlight_contact_id = int(request.args.get("highlight_contact_id"))

    alias = Alias.get(alias_id)

    # sanity check
    if not alias:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    if alias.user_id != current_user.id:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    new_contact_form = NewContactForm()

    if request.method == "POST":
        if request.form.get("form-name") == "create":
            if new_contact_form.validate():
                contact_addr = new_contact_form.email.data.strip()

                # generate a reply_email, make sure it is unique
                # not use while to avoid infinite loop
                reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
                for _ in range(1000):
                    reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
                    if not Contact.get_by(reply_email=reply_email):
                        break

                try:
                    contact_name, contact_email = parseaddr_unicode(contact_addr)
                except Exception:
                    flash(f"{contact_addr} is invalid", "error")
                    return redirect(
                        url_for("dashboard.alias_contact_manager", alias_id=alias_id,)
                    )
                contact_email = contact_email.lower()

                contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)
                # already been added
                if contact:
                    flash(f"{contact_email} is already added", "error")
                    return redirect(
                        url_for(
                            "dashboard.alias_contact_manager",
                            alias_id=alias_id,
                            highlight_contact_id=contact.id,
                        )
                    )

                contact = Contact.create(
                    user_id=alias.user_id,
                    alias_id=alias.id,
                    website_email=contact_email,
                    name=contact_name,
                    reply_email=reply_email,
                )

                LOG.d("create reverse-alias for %s", contact_addr)
                db.session.commit()
                flash(f"Reverse alias for {contact_addr} is created", "success")

                return redirect(
                    url_for(
                        "dashboard.alias_contact_manager",
                        alias_id=alias_id,
                        highlight_contact_id=contact.id,
                    )
                )
        elif request.form.get("form-name") == "delete":
            contact_id = request.form.get("contact-id")
            contact = Contact.get(contact_id)

            if not contact:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(
                    url_for("dashboard.alias_contact_manager", alias_id=alias_id)
                )
            elif contact.alias_id != alias.id:
                flash("You cannot delete reverse-alias", "warning")
                return redirect(
                    url_for("dashboard.alias_contact_manager", alias_id=alias_id)
                )

            delete_contact_email = contact.website_email
            Contact.delete(contact_id)
            db.session.commit()

            flash(
                f"Reverse-alias for {delete_contact_email} has been deleted", "success"
            )

            return redirect(
                url_for("dashboard.alias_contact_manager", alias_id=alias_id)
            )

    # make sure highlighted contact is at array start
    contacts = alias.contacts

    if highlight_contact_id:
        contacts = sorted(
            contacts, key=lambda fe: fe.id == highlight_contact_id, reverse=True
        )

    return render_template(
        "dashboard/alias_contact_manager.html",
        contacts=contacts,
        alias=alias,
        new_contact_form=new_contact_form,
        highlight_contact_id=highlight_contact_id,
    )
