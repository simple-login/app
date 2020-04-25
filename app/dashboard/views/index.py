from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from app import email_utils
from app.api.serializer import get_alias_infos_with_pagination_v2
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import (
    Alias,
    ClientUser,
    DeletedAlias,
    AliasGeneratorEnum,
    Mailbox,
)


@dashboard_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    query = request.args.get("query") or ""
    sort = request.args.get("sort") or ""

    page = 0
    if request.args.get("page"):
        page = int(request.args.get("page"))

    highlight_alias_id = None
    if request.args.get("highlight_alias_id"):
        highlight_alias_id = int(request.args.get("highlight_alias_id"))

    # User generates a new email
    if request.method == "POST":
        if request.form.get("form-name") == "trigger-email":
            alias_id = request.form.get("alias-id")
            alias = Alias.get(alias_id)

            LOG.d("trigger an email to %s", alias)
            email_utils.send_test_email_alias(alias.email, alias.user.name)

            flash(
                f"An email sent to {alias.email} is on its way, please check your inbox/spam folder",
                "success",
            )

        elif request.form.get("form-name") == "create-custom-email":
            if current_user.can_create_new_alias():
                return redirect(url_for("dashboard.custom_alias"))
            else:
                flash(f"You need to upgrade your plan to create new alias.", "warning")

        elif request.form.get("form-name") == "create-random-email":
            if current_user.can_create_new_alias():
                scheme = int(
                    request.form.get("generator_scheme") or current_user.alias_generator
                )
                if not scheme or not AliasGeneratorEnum.has_value(scheme):
                    scheme = current_user.alias_generator
                alias = Alias.create_new_random(user=current_user, scheme=scheme)

                alias.mailbox_id = current_user.default_mailbox_id

                db.session.commit()

                LOG.d("generate new email %s for user %s", alias, current_user)
                flash(f"Alias {alias.email} has been created", "success")

                return redirect(
                    url_for(
                        "dashboard.index", highlight_alias_id=alias.id, query=query,
                    )
                )
            else:
                flash(f"You need to upgrade your plan to create new alias.", "warning")

        elif request.form.get("form-name") == "switch-email-forwarding":
            alias_id = request.form.get("alias-id")
            alias: Alias = Alias.get(alias_id)

            LOG.d("switch email forwarding for %s", alias)

            alias.enabled = not alias.enabled
            if alias.enabled:
                flash(f"Alias {alias.email} is enabled", "success")
            else:
                flash(f"Alias {alias.email} is disabled", "warning")

            db.session.commit()
            return redirect(
                url_for("dashboard.index", highlight_alias_id=alias.id, query=query)
            )

        elif request.form.get("form-name") == "delete-email":
            alias_id = request.form.get("alias-id")
            alias: Alias = Alias.get(alias_id)
            if not alias:
                flash("Unknown error, sorry for the inconvenience", "error")
                return redirect(
                    url_for("dashboard.index", highlight_alias_id=alias.id, query=query)
                )

            LOG.d("delete gen email %s", alias)
            email = alias.email
            Alias.delete(alias.id)
            db.session.commit()
            flash(f"Alias {email} has been deleted", "success")

            # try to save deleted alias
            try:
                DeletedAlias.create(user_id=current_user.id, email=email)
                db.session.commit()
            # this can happen when a previously deleted alias is re-created via catch-all or directory feature
            except IntegrityError:
                LOG.error("alias %s has been added before to DeletedAlias", email)
                db.session.rollback()

        elif request.form.get("form-name") == "set-note":
            alias_id = request.form.get("alias-id")
            alias: Alias = Alias.get(alias_id)
            note = request.form.get("note")

            alias.note = note
            db.session.commit()

            flash(f"Update note for alias {alias.email}", "success")
            return redirect(
                url_for("dashboard.index", highlight_alias_id=alias.id, query=query)
            )

        elif request.form.get("form-name") == "set-mailbox":
            alias_id = request.form.get("alias-id")
            alias: Alias = Alias.get(alias_id)
            mailbox_email = request.form.get("mailbox")

            mailbox = Mailbox.get_by(email=mailbox_email)
            if not mailbox or mailbox.user_id != current_user.id:
                flash("Something went wrong, please retry", "warning")
            else:
                alias.mailbox_id = mailbox.id
                db.session.commit()
                LOG.d("Set alias %s mailbox to %s", alias, mailbox)

                flash(
                    f"Update mailbox for {alias.email} to {mailbox_email}", "success",
                )
                return redirect(
                    url_for(
                        "dashboard.index", highlight_alias_id=alias.id, query=query,
                    )
                )

        return redirect(url_for("dashboard.index", query=query))

    client_users = (
        ClientUser.filter_by(user_id=current_user.id)
        .options(joinedload(ClientUser.client))
        .options(joinedload(ClientUser.alias))
        .all()
    )

    sorted(client_users, key=lambda cu: cu.client.name)

    mailboxes = current_user.mailboxes()

    show_intro = False
    if not current_user.intro_shown:
        LOG.d("Show intro to %s", current_user)
        show_intro = True

        # to make sure not showing intro to user again
        current_user.intro_shown = True
        db.session.commit()

    return render_template(
        "dashboard/index.html",
        client_users=client_users,
        alias_infos=get_alias_infos_with_pagination_v2(current_user, page, query, sort),
        highlight_alias_id=highlight_alias_id,
        query=query,
        AliasGeneratorEnum=AliasGeneratorEnum,
        mailboxes=mailboxes,
        show_intro=show_intro,
        page=page,
        sort=sort,
    )
