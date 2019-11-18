from io import BytesIO

import arrow
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, validators

from app import s3, email_utils
from app.config import URL, EMAIL_DOMAIN
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG
from app.models import (
    PlanEnum,
    File,
    ResetPasswordCode,
    EmailChange,
    User,
    GenEmail,
    DeletedAlias,
)
from app.utils import random_string


class SettingForm(FlaskForm):
    email = StringField("Email")
    name = StringField("Name", validators=[validators.DataRequired()])
    profile_picture = FileField("Profile Picture")


class PromoCodeForm(FlaskForm):
    code = StringField("Name", validators=[validators.DataRequired()])


@dashboard_bp.route("/setting", methods=["GET", "POST"])
@login_required
def setting():
    form = SettingForm()
    promo_form = PromoCodeForm()

    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        pending_email = email_change.new_email
    else:
        pending_email = None

    if request.method == "POST":
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
                    file = File.create(path=file_path)

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

                if (
                    form.email.data
                    and form.email.data != current_user.email
                    and not pending_email
                ):
                    new_email = form.email.data

                    # check if this email is not used by other user, or as alias
                    if (
                        User.get_by(email=new_email)
                        or GenEmail.get_by(email=new_email)
                        or DeletedAlias.get_by(email=new_email)
                    ):
                        flash(f"Email {new_email} already used", "error")
                    elif new_email.endswith(EMAIL_DOMAIN):
                        flash(
                            "You cannot use alias as your personal inbox. Nice try though 😉",
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

        elif request.form.get("form-name") == "change-password":
            send_reset_password_email(current_user)

        return redirect(url_for("dashboard.setting"))

    return render_template(
        "dashboard/setting.html",
        form=form,
        PlanEnum=PlanEnum,
        promo_form=promo_form,
        pending_email=pending_email,
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

    flash(
        "You are going to receive an email containing instruction to change your password",
        "success",
    )


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
        flash("Your email change is cancelled", "success")
        return redirect(url_for("dashboard.setting"))
    else:
        flash(
            "You have no pending email change. Redirect back to Setting page", "warning"
        )
        return redirect(url_for("dashboard.setting"))
