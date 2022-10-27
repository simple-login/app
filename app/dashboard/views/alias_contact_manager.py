from dataclasses import dataclass
from operator import or_

from flask import render_template, request, redirect, flash
from flask import url_for
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from sqlalchemy import and_, func, case
from wtforms import StringField, validators, ValidationError

# Need to import directly from config to allow modification from the tests
from app import config, parallel_limiter
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.email_utils import (
    is_valid_email,
    generate_reply_email,
    parse_full_address,
)
from app.errors import (
    CannotCreateContactForReverseAlias,
    ErrContactErrorUpgradeNeeded,
    ErrAddressInvalid,
    ErrContactAlreadyExists,
)
from app.log import LOG
from app.models import Alias, Contact, EmailLog, User
from app.utils import sanitize_email, CSRFValidationForm


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


def user_can_create_contacts(user: User) -> bool:
    if user.is_premium():
        return True
    if user.flags & User.FLAG_FREE_DISABLE_CREATE_ALIAS == 0:
        return True
    return not config.DISABLE_CREATE_CONTACTS_FOR_FREE_USERS


def create_contact(user: User, alias: Alias, contact_address: str) -> Contact:
    """
    Create a contact for a user. Can be restricted for new free users by enabling DISABLE_CREATE_CONTACTS_FOR_FREE_USERS.
    Can throw exceptions:
     - ErrAddressInvalid
     - ErrContactAlreadyExists
     - ErrContactUpgradeNeeded - If DISABLE_CREATE_CONTACTS_FOR_FREE_USERS this exception will be raised for new free users
    """
    if not contact_address:
        raise ErrAddressInvalid("Empty address")
    try:
        contact_name, contact_email = parse_full_address(contact_address)
    except ValueError:
        raise ErrAddressInvalid(contact_address)

    contact_email = sanitize_email(contact_email)
    if not is_valid_email(contact_email):
        raise ErrAddressInvalid(contact_email)

    contact = Contact.get_by(alias_id=alias.id, website_email=contact_email)
    if contact:
        raise ErrContactAlreadyExists(contact)

    if not user_can_create_contacts(user):
        raise ErrContactErrorUpgradeNeeded()

    contact = Contact.create(
        user_id=alias.user_id,
        alias_id=alias.id,
        website_email=contact_email,
        name=contact_name,
        reply_email=generate_reply_email(contact_email, user),
    )

    LOG.d(
        "create reverse-alias for %s %s, reverse alias:%s",
        contact_address,
        alias,
        contact.reply_email,
    )
    Session.commit()

    return contact


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


def get_contact_infos(
    alias: Alias, page=0, contact_id=None, query: str = ""
) -> [ContactInfo]:
    """if contact_id is set, only return the contact info for this contact"""
    sub = (
        Session.query(
            Contact.id,
            func.sum(case([(EmailLog.is_reply, 1)], else_=0)).label("nb_reply"),
            func.sum(
                case(
                    [
                        (
                            and_(
                                EmailLog.is_reply.is_(False),
                                EmailLog.blocked.is_(False),
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
        Session.query(
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
                sub.c.max_email_log_created_at.is_(None),
            )
        )
    )

    if query:
        q = q.filter(
            or_(
                Contact.website_email.ilike(f"%{query}%"),
                Contact.name.ilike(f"%{query}%"),
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
    q = (
        q.order_by(latest_activity.desc())
        .limit(config.PAGE_LIMIT)
        .offset(page * config.PAGE_LIMIT)
    )

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


def delete_contact(alias: Alias, contact_id: int):
    contact = Contact.get(contact_id)

    if not contact:
        flash("Unknown error. Refresh the page", "warning")
    elif contact.alias_id != alias.id:
        flash("You cannot delete reverse-alias", "warning")
    else:
        delete_contact_email = contact.website_email
        Contact.delete(contact_id)
        Session.commit()

        flash(f"Reverse-alias for {delete_contact_email} has been deleted", "success")


@dashboard_bp.route("/alias_contact_manager/<int:alias_id>/", methods=["GET", "POST"])
@login_required
@parallel_limiter.lock(name="contact_creation")
def alias_contact_manager(alias_id):
    highlight_contact_id = None
    if request.args.get("highlight_contact_id"):
        try:
            highlight_contact_id = int(request.args.get("highlight_contact_id"))
        except ValueError:
            flash("Invalid contact id", "error")
            return redirect(url_for("dashboard.index"))

    alias = Alias.get(alias_id)

    page = 0
    if request.args.get("page"):
        page = int(request.args.get("page"))

    query = request.args.get("query") or ""

    # sanity check
    if not alias:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    if alias.user_id != current_user.id:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    new_contact_form = NewContactForm()
    csrf_form = CSRFValidationForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "create":
            if new_contact_form.validate():
                contact_address = new_contact_form.email.data.strip()
                try:
                    contact = create_contact(current_user, alias, contact_address)
                except (
                    ErrContactErrorUpgradeNeeded,
                    ErrAddressInvalid,
                    ErrContactAlreadyExists,
                    CannotCreateContactForReverseAlias,
                ) as excp:
                    flash(excp.error_for_user(), "error")
                    return redirect(request.url)
                flash(f"Reverse alias for {contact_address} is created", "success")
                return redirect(
                    url_for(
                        "dashboard.alias_contact_manager",
                        alias_id=alias_id,
                        highlight_contact_id=contact.id,
                    )
                )
        elif request.form.get("form-name") == "delete":
            contact_id = request.form.get("contact-id")
            delete_contact(alias, contact_id)
            return redirect(
                url_for("dashboard.alias_contact_manager", alias_id=alias_id)
            )

        elif request.form.get("form-name") == "search":
            query = request.form.get("query")
            return redirect(
                url_for(
                    "dashboard.alias_contact_manager",
                    alias_id=alias_id,
                    query=query,
                    highlight_contact_id=highlight_contact_id,
                )
            )

    contact_infos = get_contact_infos(alias, page, query=query)
    last_page = len(contact_infos) < config.PAGE_LIMIT
    nb_contact = Contact.filter(Contact.alias_id == alias.id).count()

    # if highlighted contact isn't included, fetch it
    # make sure highlighted contact is at array start
    contact_ids = [contact_info.contact.id for contact_info in contact_infos]
    if highlight_contact_id and highlight_contact_id not in contact_ids:
        contact_infos = (
            get_contact_infos(alias, contact_id=highlight_contact_id, query=query)
            + contact_infos
        )

    return render_template(
        "dashboard/alias_contact_manager.html",
        contact_infos=contact_infos,
        alias=alias,
        new_contact_form=new_contact_form,
        highlight_contact_id=highlight_contact_id,
        page=page,
        last_page=last_page,
        query=query,
        nb_contact=nb_contact,
        can_create_contacts=user_can_create_contacts(current_user),
        csrf_form=csrf_form,
    )
