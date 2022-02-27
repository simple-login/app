from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import (
    EMAIL_DOMAIN,
    ALIAS_DOMAINS,
    MAX_NB_DIRECTORY,
    BOUNCE_PREFIX_FOR_REPLY_PHASE,
)
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.errors import DirectoryInTrashError
from app.models import Directory, Mailbox, DirectoryMailbox


class NewDirForm(FlaskForm):
    name = StringField(
        "name", validators=[validators.DataRequired(), validators.Length(min=3)]
    )


@dashboard_bp.route("/directory", methods=["GET", "POST"])
@login_required
def directory():
    dirs = (
        Directory.filter_by(user_id=current_user.id)
        .order_by(Directory.created_at.desc())
        .all()
    )

    mailboxes = current_user.mailboxes()

    new_dir_form = NewDirForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            dir_id = request.form.get("dir-id")
            dir = Directory.get(dir_id)

            if not dir:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))
            elif dir.user_id != current_user.id:
                flash("You cannot delete this directory", "warning")
                return redirect(url_for("dashboard.directory"))

            name = dir.name
            Directory.delete(dir_id)
            Session.commit()
            flash(f"Directory {name} has been deleted", "success")

            return redirect(url_for("dashboard.directory"))

        if request.form.get("form-name") == "toggle-directory":
            dir_id = request.form.get("dir-id")
            dir = Directory.get(dir_id)

            if not dir or dir.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))

            if request.form.get("dir-status") == "on":
                dir.disabled = False
                flash(f"On-the-fly is enabled for {dir.name}", "success")
            else:
                dir.disabled = True
                flash(f"On-the-fly is disabled for {dir.name}", "warning")

            Session.commit()

            return redirect(url_for("dashboard.directory"))

        elif request.form.get("form-name") == "update":
            dir_id = request.form.get("dir-id")
            dir = Directory.get(dir_id)

            if not dir or dir.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))

            mailbox_ids = request.form.getlist("mailbox_ids")
            # check if mailbox is not tempered with
            mailboxes = []
            for mailbox_id in mailbox_ids:
                mailbox = Mailbox.get(mailbox_id)
                if (
                    not mailbox
                    or mailbox.user_id != current_user.id
                    or not mailbox.verified
                ):
                    flash("Something went wrong, please retry", "warning")
                    return redirect(url_for("dashboard.directory"))
                mailboxes.append(mailbox)

            if not mailboxes:
                flash("You must select at least 1 mailbox", "warning")
                return redirect(url_for("dashboard.directory"))

            # first remove all existing directory-mailboxes links
            DirectoryMailbox.filter_by(directory_id=dir.id).delete()
            Session.flush()

            for mailbox in mailboxes:
                DirectoryMailbox.create(directory_id=dir.id, mailbox_id=mailbox.id)

            Session.commit()
            flash(f"Directory {dir.name} has been updated", "success")

            return redirect(url_for("dashboard.directory"))
        elif request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add directory", "warning")
                return redirect(url_for("dashboard.directory"))

            if current_user.directory_quota <= 0:
                flash(
                    f"You cannot have more than {MAX_NB_DIRECTORY} directories",
                    "warning",
                )
                return redirect(url_for("dashboard.directory"))

            if new_dir_form.validate():
                new_dir_name = new_dir_form.name.data.lower()

                if Directory.get_by(name=new_dir_name):
                    flash(f"{new_dir_name} already used", "warning")
                elif new_dir_name in (
                    "reply",
                    "ra",
                    "bounces",
                    "bounce",
                    "transactional",
                    BOUNCE_PREFIX_FOR_REPLY_PHASE,
                ):
                    flash(
                        "this directory name is reserved, please choose another name",
                        "warning",
                    )
                else:
                    try:
                        new_dir = Directory.create(
                            name=new_dir_name, user_id=current_user.id
                        )
                    except DirectoryInTrashError:
                        flash(
                            f"{new_dir_name} has been used before and cannot be reused",
                            "error",
                        )
                    else:
                        Session.commit()
                        mailbox_ids = request.form.getlist("mailbox_ids")
                        if mailbox_ids:
                            # check if mailbox is not tempered with
                            mailboxes = []
                            for mailbox_id in mailbox_ids:
                                mailbox = Mailbox.get(mailbox_id)
                                if (
                                    not mailbox
                                    or mailbox.user_id != current_user.id
                                    or not mailbox.verified
                                ):
                                    flash(
                                        "Something went wrong, please retry", "warning"
                                    )
                                    return redirect(url_for("dashboard.directory"))
                                mailboxes.append(mailbox)

                            for mailbox in mailboxes:
                                DirectoryMailbox.create(
                                    directory_id=new_dir.id, mailbox_id=mailbox.id
                                )

                            Session.commit()

                        flash(f"Directory {new_dir.name} is created", "success")

                    return redirect(url_for("dashboard.directory"))

    return render_template(
        "dashboard/directory.html",
        dirs=dirs,
        new_dir_form=new_dir_form,
        mailboxes=mailboxes,
        EMAIL_DOMAIN=EMAIL_DOMAIN,
        ALIAS_DOMAINS=ALIAS_DOMAINS,
    )
