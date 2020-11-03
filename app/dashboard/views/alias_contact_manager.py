import re
from dataclasses import dataclass
from operator import or_

from flask import render_template, request, redirect, flash
from flask import url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from sqlalchemy import and_, func, case
from wtforms import StringField, validators, ValidationError

from app.config import EMAIL_DOMAIN, PAGE_LIMIT
from app.dashboard.base import dashboard_bp
from app.email_utils import parseaddr_unicode, is_valid_email
from app.extensions import db
from app.log import LOG
from app.models import Alias, Contact, EmailLog
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

        if not is_valid_email(email_part):
            raise ValidationError(message)

    return _check


class NewContactForm(FlaskForm):
    email = StringField(
        "Email", validators=[validators.DataRequired(), email_validator()]
    )


@dataclass
class ContactInfo(object):
    contact: Contact

    nb_forward: int
    nb_reply: int

    latest_email_log: EmailLog


def get_contact_infos(alias: Alias, page=0, contact_id=None) -> [ContactInfo]:
    """if contact_id is set, only return the contact info for this contact"""
    sub = (
        db.session.query(
            Contact.id,
            func.sum(case([(EmailLog.is_reply, 1)], else_=0)).label("nb_reply"),
            func.sum(
                case(
                    [
                        (
                            and_(
                                EmailLog.is_reply == False,
                                EmailLog.blocked == False,
                            ),
                            1,
                        )
                    ],
                    else_=0,
                )
            ).label("nb_forward"),
            func.max(EmailLog.created_at).label("max_email_log_created_at"),
        )
        .join(
            EmailLog,
            EmailLog.contact_id == Contact.id,
            isouter=True,
        )
        .filter(Contact.alias_id == alias.id)
        .group_by(Contact.id)
        .subquery()
    )

    q = (
        db.session.query(
            Contact,
            EmailLog,
            sub.c.nb_reply,
            sub.c.nb_forward,
        )
        .join(
            EmailLog,
            EmailLog.contact_id == Contact.id,
            isouter=True,
        )
        .filter(Contact.alias_id == alias.id)
        .filter(Contact.id == sub.c.id)
        .filter(
            or_(
                EmailLog.created_at == sub.c.max_email_log_created_at,
                # no email log yet for this contact
                sub.c.max_email_log_created_at == None,
            )
        )
    )

    if contact_id:
        q = q.filter(Contact.id == contact_id)

    latest_activity = case(
        [
            (EmailLog.created_at > Contact.created_at, EmailLog.created_at),
            (EmailLog.created_at < Contact.created_at, Contact.created_at),
        ],
        else_=Contact.created_at,
    )
    q = q.order_by(latest_activity.desc()).limit(PAGE_LIMIT).offset(page * PAGE_LIMIT)

    ret = []
    for contact, latest_email_log, nb_reply, nb_forward in q:
        contact_info = ContactInfo(
            contact=contact,
            nb_forward=nb_forward,
            nb_reply=nb_reply,
            latest_email_log=latest_email_log,
        )
        ret.append(contact_info)

    return ret


@dashboard_bp.route("/alias_contact_manager/<alias_id>/", methods=["GET", "POST"])
@login_required
def alias_contact_manager(alias_id):
    highlight_contact_id = None
    if request.args.get("highlight_contact_id"):
        highlight_contact_id = int(request.args.get("highlight_contact_id"))

    alias = Alias.get(alias_id)

    page = 0
    if request.args.get("page"):
        page = int(request.args.get("page"))

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
                        url_for(
                            "dashboard.alias_contact_manager",
                            alias_id=alias_id,
                        )
                    )

                if not is_valid_email(contact_email):
                    flash(f"{contact_email} is invalid", "error")
                    return redirect(
                        url_for(
                            "dashboard.alias_contact_manager",
                            alias_id=alias_id,
                        )
                    )

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

    contact_infos = get_contact_infos(alias, page)
    last_page = len(contact_infos) < PAGE_LIMIT

    # if highlighted contact isn't included, fetch it
    # make sure highlighted contact is at array start
    contact_ids = [contact_info.contact.id for contact_info in contact_infos]
    if highlight_contact_id and highlight_contact_id not in contact_ids:
        contact_infos = (
            get_contact_infos(alias, contact_id=highlight_contact_id) + contact_infos
        )

    return render_template(
        "dashboard/alias_contact_manager.html",
        contact_infos=contact_infos,
        alias=alias,
        new_contact_form=new_contact_form,
        highlight_contact_id=highlight_contact_id,
        page=page,
        last_page=last_page,
    )
