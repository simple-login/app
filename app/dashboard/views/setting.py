from io import BytesIO

import arrow
import stripe
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, validators

from app import s3, email_utils
from app.config import URL, PROMO_CODE
from app.dashboard.base import dashboard_bp
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import PlanEnum, File, ResetPasswordCode
from app.utils import random_string


class SettingForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])
    profile_picture = FileField("Profile Picture")


class PromoCodeForm(FlaskForm):
    code = StringField("Name", validators=[validators.DataRequired()])


@dashboard_bp.route("/setting", methods=["GET", "POST"])
@login_required
def setting():
    form = SettingForm()
    promo_form = PromoCodeForm()

    if request.method == "POST":
        if request.form.get("form-name") == "update-profile":
            if form.validate():
                # update user info
                current_user.name = form.name.data

                if form.profile_picture.data:
                    file_path = random_string(30)
                    file = File.create(path=file_path)

                    s3.upload_from_bytesio(
                        file_path, BytesIO(form.profile_picture.data.read())
                    )

                    db.session.flush()
                    LOG.d("upload file %s to s3", file)

                    current_user.profile_picture_id = file.id
                    db.session.flush()

                db.session.commit()
                flash(f"Your profile has been updated", "success")
        
        elif request.form.get("form-name") == "change-password":
            send_reset_password_email(current_user)
        

        return redirect(url_for("dashboard.setting"))

    return render_template(
        "dashboard/setting.html", form=form, PlanEnum=PlanEnum, promo_form=promo_form
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

    email_utils.send_by_sendgrid(
        user.email,
        f"Reset your password on SimpleLogin",
        html_content=f"""
    Hi {user.name}! <br><br>

    To reset or change your password, please follow this link <a href="{reset_password_link}">reset password</a>. 
    Or you can paste this link into your browser: <br><br>

    {reset_password_link} <br><br>

    Cheers,
    SimpleLogin team.
    """,
    )

    flash(
        "You are going to receive an email containing instruction to change your password",
        "success",
    )
