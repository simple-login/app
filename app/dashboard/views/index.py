from dataclasses import dataclass

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import alias_utils, parallel_limiter
from app.api.serializer import get_alias_infos_with_pagination_v3, get_alias_info_v3
from app.config import ALIAS_LIMIT, PAGE_LIMIT
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import (
    Alias,
    AliasGeneratorEnum,
    User,
    EmailLog,
    Contact,
)
from app.utils import CSRFValidationForm


@dataclass
class Stats:
    nb_alias: int
    nb_forward: int
    nb_reply: int
    nb_block: int


def get_stats(user: User) -> Stats:
    nb_alias = Alias.filter_by(user_id=user.id).count()
    nb_forward = (
        Session.query(EmailLog)
        .filter_by(user_id=user.id, is_reply=False, blocked=False, bounced=False)
        .count()
    )
    nb_reply = (
        Session.query(EmailLog)
        .filter_by(user_id=user.id, is_reply=True, blocked=False, bounced=False)
        .count()
    )
    nb_block = (
        Session.query(EmailLog)
        .filter_by(user_id=user.id, is_reply=False, blocked=True, bounced=False)
        .count()
    )

    return Stats(
        nb_alias=nb_alias, nb_forward=nb_forward, nb_reply=nb_reply, nb_block=nb_block
    )


@dashboard_bp.route("/", methods=["GET", "POST"])
@limiter.limit(
    ALIAS_LIMIT,
    methods=["POST"],
    exempt_when=lambda: request.form.get("form-name") != "create-random-email",
)
@login_required
@parallel_limiter.lock(
    name="alias_creation",
    only_when=lambda: request.form.get("form-name") == "create-random-email",
)
def index():
    query = request.args.get("query") or ""
    sort = request.args.get("sort") or ""
    alias_filter = request.args.get("filter") or ""

    page = 0
    if request.args.get("page"):
        page = int(request.args.get("page"))

    highlight_alias_id = None
    if request.args.get("highlight_alias_id"):
        try:
            highlight_alias_id = int(request.args.get("highlight_alias_id"))
        except ValueError:
            LOG.w(
                "highlight_alias_id must be a number, received %s",
                request.args.get("highlight_alias_id"),
            )
    csrf_form = CSRFValidationForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "create-custom-email":
            if current_user.can_create_new_alias():
                return redirect(url_for("dashboard.custom_alias"))
            else:
                flash("You need to upgrade your plan to create new alias.", "warning")

        elif request.form.get("form-name") == "create-random-email":
            if current_user.can_create_new_alias():
                scheme = int(
                    request.form.get("generator_scheme") or current_user.alias_generator
                )
                if not scheme or not AliasGeneratorEnum.has_value(scheme):
                    scheme = current_user.alias_generator
                alias = Alias.create_new_random(user=current_user, scheme=scheme)

                alias.mailbox_id = current_user.default_mailbox_id

                Session.commit()

                LOG.d("create new random alias %s for user %s", alias, current_user)
                flash(f"Alias {alias.email} has been created", "success")

                return redirect(
                    url_for(
                        "dashboard.index",
                        highlight_alias_id=alias.id,
                        query=query,
                        sort=sort,
                        filter=alias_filter,
                    )
                )
            else:
                flash("You need to upgrade your plan to create new alias.", "warning")

        elif request.form.get("form-name") in ("delete-alias", "disable-alias"):
            try:
                alias_id = int(request.form.get("alias-id"))
            except ValueError:
                flash("unknown error", "error")
                return redirect(request.url)

            alias: Alias = Alias.get(alias_id)
            if not alias or alias.user_id != current_user.id:
                flash("Unknown error, sorry for the inconvenience", "error")
                return redirect(
                    url_for(
                        "dashboard.index",
                        query=query,
                        sort=sort,
                        filter=alias_filter,
                    )
                )

            if request.form.get("form-name") == "delete-alias":
                LOG.d("delete alias %s", alias)
                email = alias.email
                alias_utils.delete_alias(alias, current_user)
                flash(f"Alias {email} has been deleted", "success")
            elif request.form.get("form-name") == "disable-alias":
                alias.enabled = False
                Session.commit()
                flash(f"Alias {alias.email} has been disabled", "success")

        return redirect(
            url_for("dashboard.index", query=query, sort=sort, filter=alias_filter)
        )

    mailboxes = current_user.mailboxes()

    show_intro = False
    if not current_user.intro_shown:
        LOG.d("Show intro to %s", current_user)
        show_intro = True

        # to make sure not showing intro to user again
        current_user.intro_shown = True
        Session.commit()

    stats = get_stats(current_user)

    mailbox_id = None
    if alias_filter and alias_filter.startswith("mailbox:"):
        mailbox_id = int(alias_filter[len("mailbox:") :])

    directory_id = None
    if alias_filter and alias_filter.startswith("directory:"):
        directory_id = int(alias_filter[len("directory:") :])

    alias_infos = get_alias_infos_with_pagination_v3(
        current_user,
        page,
        query,
        sort,
        alias_filter,
        mailbox_id,
        directory_id,
        # load 1 alias more to know whether this is the last page
        page_limit=PAGE_LIMIT + 1,
    )

    last_page = len(alias_infos) <= PAGE_LIMIT
    # remove the last alias that's added to know whether this is the last page
    alias_infos = alias_infos[:PAGE_LIMIT]

    # add highlighted alias in case it's not included
    if highlight_alias_id and highlight_alias_id not in [
        alias_info.alias.id for alias_info in alias_infos
    ]:
        highlight_alias_info = get_alias_info_v3(
            current_user, alias_id=highlight_alias_id
        )
        if highlight_alias_info:
            alias_infos.insert(0, highlight_alias_info)

    return render_template(
        "dashboard/index.html",
        alias_infos=alias_infos,
        highlight_alias_id=highlight_alias_id,
        query=query,
        AliasGeneratorEnum=AliasGeneratorEnum,
        mailboxes=mailboxes,
        show_intro=show_intro,
        page=page,
        last_page=last_page,
        sort=sort,
        filter=alias_filter,
        stats=stats,
        csrf_form=csrf_form,
    )


@dashboard_bp.route("/contacts/<int:contact_id>/toggle", methods=["POST"])
@login_required
def toggle_contact(contact_id):
    """
    Block/Unblock contact
    """
    contact = Contact.get(contact_id)

    if not contact or contact.alias.user_id != current_user.id:
        return "Forbidden", 403

    contact.block_forward = not contact.block_forward
    Session.commit()

    if contact.block_forward:
        toast_msg = f"{contact.website_email} can no longer send emails to {contact.alias.email}"
    else:
        toast_msg = (
            f"{contact.website_email} can now send emails to {contact.alias.email}"
        )

    return render_template(
        "partials/toggle_contact.html", contact=contact, toast_msg=toast_msg
    )
