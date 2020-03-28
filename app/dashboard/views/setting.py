import json
from io import BytesIO

import arrow
from flask import render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user, logout_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, validators
from wtforms.fields.html5 import EmailField

from app import s3, email_utils
from app.config import URL
from app.dashboard.base import dashboard_bp
from app.email_utils import can_be_used_as_personal_email, email_already_used
from app.extensions import db
from app.log import LOG
from app.models import (
    PlanEnum,
    File,
    ResetPasswordCode,
    EmailChange,
    User,
    Alias,
    DeletedAlias,
    CustomDomain,
    Client,
    AliasGeneratorEnum,
    ManualSubscription,
)
from app.utils import random_string


class SettingForm(FlaskForm):
    name = StringField("Name")
    profile_picture = FileField("Profile Picture")


class ChangeEmailForm(FlaskForm):
    email = EmailField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


class PromoCodeForm(FlaskForm):
    code = StringField("Name", validators=[validators.DataRequired()])


@dashboard_bp.route("/setting", methods=["GET", "POST"])
@login_required
def setting():
    form = SettingForm()
    promo_form = PromoCodeForm()
    change_email_form = ChangeEmailForm()

    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        pending_email = email_change.new_email
    else:
        pending_email = None

    if request.method == "POST":
        if request.form.get("form-name") == "update-email":
            if change_email_form.validate():
                if (
                    change_email_form.email.data != current_user.email
                    and not pending_email
                ):
                    new_email = change_email_form.email.data

                    # check if this email is not already used
                    if (
                        email_already_used(new_email)
                        or Alias.get_by(email=new_email)
                        or DeletedAlias.get_by(email=new_email)
                    ):
                        flash(f"Email {new_email} already used", "error")
                    elif not can_be_used_as_personal_email(new_email):
                        flash(
                            "You cannot use this email address as your personal inbox.",
                            "error",
                        )
                    else:
                        email_change = EmailChange.create(
                            user_id=current_user.id,
                            code=random_string(
                                60
                            ),  # todo: make sure the code is unique
                            new_email=new_email,
                        )
                        db.session.commit()
                        send_change_email_confirmation(current_user, email_change)
                        flash(
                            "A confirmation email is on the way, please check your inbox",
                            "success",
                        )
                        return redirect(url_for("dashboard.setting"))
        if request.form.get("form-name") == "update-profile":
            if form.validate():
                profile_updated = False
                # update user info
                if form.name.data != current_user.name:
                    current_user.name = form.name.data
                    db.session.commit()
                    profile_updated = True

                if form.profile_picture.data:
                    file_path = random_string(30)
                    file = File.create(user_id=current_user.id, path=file_path)

                    s3.upload_from_bytesio(
                        file_path, BytesIO(form.profile_picture.data.read())
                    )

                    db.session.flush()
                    LOG.d("upload file %s to s3", file)

                    current_user.profile_picture_id = file.id
                    db.session.commit()
                    profile_updated = True

                if profile_updated:
                    flash(f"Your profile has been updated", "success")
                    return redirect(url_for("dashboard.setting"))

        elif request.form.get("form-name") == "change-password":
            flash(
                "You are going to receive an email containing instructions to change your password",
                "success",
            )
            send_reset_password_email(current_user)
            return redirect(url_for("dashboard.setting"))

        elif request.form.get("form-name") == "notification-preference":
            choose = request.form.get("notification")
            if choose == "on":
                current_user.notification = True
            else:
                current_user.notification = False
            db.session.commit()
            flash("Your notification preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))

        elif request.form.get("form-name") == "delete-account":
            User.delete(current_user.id)
            db.session.commit()
            flash("Your account has been deleted", "success")
            logout_user()
            return redirect(url_for("auth.register"))

        elif request.form.get("form-name") == "change-alias-generator":
            scheme = int(request.form.get("alias-generator-scheme"))
            if AliasGeneratorEnum.has_value(scheme):
                current_user.alias_generator = scheme
                db.session.commit()
            flash("Your preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))
        elif request.form.get("form-name") == "change-sender-format":
            sender_format = int(request.form.get("sender-format"))
            if sender_format == 0:
                current_user.use_via_format_for_sender = False
            else:
                current_user.use_via_format_for_sender = True
            db.session.commit()
            flash("Your sender format preference has been updated", "success")
            return redirect(url_for("dashboard.setting"))

        elif request.form.get("form-name") == "export-data":
            data = {
                "email": current_user.email,
                "name": current_user.name,
                "aliases": [],
                "apps": [],
                "custom_domains": [],
            }

            for alias in Alias.filter_by(user_id=current_user.id).all():  # type: Alias
                data["aliases"].append(dict(email=alias.email, enabled=alias.enabled))

            for custom_domain in CustomDomain.filter_by(user_id=current_user.id).all():
                data["custom_domains"].append(custom_domain.domain)

            for app in Client.filter_by(user_id=current_user.id):  # type: Client
                data["apps"].append(
                    dict(name=app.name, home_url=app.home_url, published=app.published)
                )

            return Response(
                json.dumps(data),
                mimetype="text/json",
                headers={"Content-Disposition": "attachment;filename=data.json"},
            )

    manual_sub = ManualSubscription.get_by(user_id=current_user.id)
    return render_template(
        "dashboard/setting.html",
        form=form,
        PlanEnum=PlanEnum,
        promo_form=promo_form,
        change_email_form=change_email_form,
        pending_email=pending_email,
        AliasGeneratorEnum=AliasGeneratorEnum,
        manual_sub=manual_sub,
    )


def send_reset_password_email(user):
    """
    generate a new ResetPasswordCode and send it over email to user
    """
    # the activation code is valid for 1h
    reset_password_code = ResetPasswordCode.create(
        user_id=user.id, code=random_string(60)
    )
    db.session.commit()

    reset_password_link = f"{URL}/auth/reset_password?code={reset_password_code.code}"

    email_utils.send_reset_password_email(user.email, user.name, reset_password_link)


def send_change_email_confirmation(user: User, email_change: EmailChange):
    """
    send confirmation email to the new email address
    """

    link = f"{URL}/auth/change_email?code={email_change.code}"

    email_utils.send_change_email(email_change.new_email, user.email, user.name, link)


@dashboard_bp.route("/resend_email_change", methods=["GET", "POST"])
@login_required
def resend_email_change():
    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        # extend email change expiration
        email_change.expired = arrow.now().shift(hours=12)
        db.session.commit()

        send_change_email_confirmation(current_user, email_change)
        flash("A confirmation email is on the way, please check your inbox", "success")
        return redirect(url_for("dashboard.setting"))
    else:
        flash(
            "You have no pending email change. Redirect back to Setting page", "warning"
        )
        return redirect(url_for("dashboard.setting"))


@dashboard_bp.route("/cancel_email_change", methods=["GET", "POST"])
@login_required
def cancel_email_change():
    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        EmailChange.delete(email_change.id)
        db.session.commit()
        flash("Your email change is cancelled", "success")
        return redirect(url_for("dashboard.setting"))
    else:
        flash(
            "You have no pending email change. Redirect back to Setting page", "warning"
        )
        return redirect(url_for("dashboard.setting"))
