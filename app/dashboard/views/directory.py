from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    validators,
    SelectMultipleField,
    BooleanField,
    IntegerField,
)

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


class ToggleDirForm(FlaskForm):
    directory_id = IntegerField(validators=[validators.DataRequired()])
    directory_enabled = BooleanField(validators=[])


class UpdateDirForm(FlaskForm):
    directory_id = IntegerField(validators=[validators.DataRequired()])
    mailbox_ids = SelectMultipleField(
        validators=[validators.DataRequired()], validate_choice=False, choices=[]
    )


class DeleteDirForm(FlaskForm):
    directory_id = IntegerField(validators=[validators.DataRequired()])


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
    toggle_dir_form = ToggleDirForm()
    update_dir_form = UpdateDirForm()
    update_dir_form.mailbox_ids.choices = [
        (str(mailbox.id), str(mailbox.id)) for mailbox in mailboxes
    ]
    delete_dir_form = DeleteDirForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            if not delete_dir_form.validate():
                flash(f"Invalid request", "warning")
                return redirect(url_for("dashboard.directory"))
            dir_obj = Directory.get(delete_dir_form.directory_id.data)

            if not dir_obj:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))
            elif dir_obj.user_id != current_user.id:
                flash("You cannot delete this directory", "warning")
                return redirect(url_for("dashboard.directory"))

            name = dir_obj.name
            Directory.delete(dir_obj.id)
            Session.commit()
            flash(f"Directory {name} has been deleted", "success")

            return redirect(url_for("dashboard.directory"))

        if request.form.get("form-name") == "toggle-directory":
            if not toggle_dir_form.validate():
                flash(f"Invalid request", "warning")
                return redirect(url_for("dashboard.directory"))
            dir_id = toggle_dir_form.directory_id.data
            dir_obj = Directory.get(dir_id)

            if not dir_obj or dir_obj.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))

            if toggle_dir_form.directory_enabled.data:
                dir_obj.disabled = False
                flash(f"On-the-fly is enabled for {dir_obj.name}", "success")
            else:
                dir_obj.disabled = True
                flash(f"On-the-fly is disabled for {dir_obj.name}", "warning")

            Session.commit()

            return redirect(url_for("dashboard.directory"))

        elif request.form.get("form-name") == "update":
            if not update_dir_form.validate():
                flash(f"Invalid request", "warning")
                return redirect(url_for("dashboard.directory"))
            dir_id = update_dir_form.directory_id.data
            dir_obj = Directory.get(dir_id)

            if not dir_obj or dir_obj.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.directory"))

            mailbox_ids = update_dir_form.mailbox_ids.data
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
            DirectoryMailbox.filter_by(directory_id=dir_obj.id).delete()
            Session.flush()

            for mailbox in mailboxes:
                DirectoryMailbox.create(directory_id=dir_obj.id, mailbox_id=mailbox.id)

            Session.commit()
            flash(f"Directory {dir_obj.name} has been updated", "success")

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
        toggle_dir_form=toggle_dir_form,
        update_dir_form=update_dir_form,
        delete_dir_form=delete_dir_form,
        new_dir_form=new_dir_form,
        mailboxes=mailboxes,
        EMAIL_DOMAIN=EMAIL_DOMAIN,
        ALIAS_DOMAINS=ALIAS_DOMAINS,
    )
