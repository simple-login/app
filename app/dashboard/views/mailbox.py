import base64
import binascii
import json
from typing import Optional

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import TimestampSigner
from wtforms import validators, IntegerField
from wtforms.fields.html5 import EmailField

from app import parallel_limiter, mailbox_utils, user_settings
from app.config import MAILBOX_SECRET
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.models import Mailbox
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.utils import CSRFValidationForm


class NewMailboxForm(FlaskForm):
    email = EmailField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


class DeleteMailboxForm(FlaskForm):
    mailbox_id = IntegerField(
        validators=[validators.DataRequired()],
    )
    transfer_mailbox_id = IntegerField()


@dashboard_bp.route("/mailbox", methods=["GET", "POST"])
@login_required
@parallel_limiter.lock(only_when=lambda: request.method == "POST")
def mailbox_route():
    mailboxes = (
        Mailbox.filter_by(user_id=current_user.id)
        .order_by(Mailbox.created_at.desc())
        .all()
    )

    new_mailbox_form = NewMailboxForm()
    csrf_form = CSRFValidationForm()
    delete_mailbox_form = DeleteMailboxForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            if not delete_mailbox_form.validate():
                flash("Invalid request", "warning")
                return redirect(request.url)
            mailbox = Mailbox.get(delete_mailbox_form.mailbox_id.data)
            if mailbox and mailbox.is_admin_disabled():
                flash(
                    "You cannot modify that mailbox. Please contact support.", "error"
                )
                return redirect(url_for("dashboard.mailbox_route"))
            try:
                mailbox = mailbox_utils.delete_mailbox(
                    current_user,
                    delete_mailbox_form.mailbox_id.data,
                    delete_mailbox_form.transfer_mailbox_id.data,
                )
            except mailbox_utils.MailboxError as e:
                flash(e.msg, "warning")
                return redirect(url_for("dashboard.mailbox_route"))
            flash(
                f"Mailbox {mailbox.email} scheduled for deletion."
                f"You will receive a confirmation email when the deletion is finished",
                "success",
            )
            return redirect(url_for("dashboard.mailbox_route"))

        if request.form.get("form-name") == "set-default":
            if not csrf_form.validate():
                flash("Invalid request", "warning")
                return redirect(request.url)
            mailbox_id = request.form.get("mailbox_id")
            mailbox = Mailbox.get(mailbox_id)
            if mailbox and mailbox.is_admin_disabled():
                flash(
                    "You cannot modify that mailbox. Please contact support.", "error"
                )
                return redirect(url_for("dashboard.mailbox_route"))
            try:
                mailbox = user_settings.set_default_mailbox(current_user, mailbox_id)
            except user_settings.CannotSetMailbox as e:
                flash(e.msg, "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            flash(f"Mailbox {mailbox.email} is set as Default Mailbox", "success")

            return redirect(url_for("dashboard.mailbox_route"))

        elif request.form.get("form-name") == "create":
            if not new_mailbox_form.validate():
                flash("Invalid request", "warning")
                return redirect(request.url)
            mailbox_email = new_mailbox_form.email.data.lower().strip().replace(" ", "")
            try:
                mailbox = mailbox_utils.create_mailbox(
                    current_user, mailbox_email
                ).mailbox
            except mailbox_utils.MailboxError as e:
                flash(e.msg, "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            flash(
                f"You are going to receive an email to confirm {mailbox.email}.",
                "success",
            )

            return redirect(
                url_for(
                    "dashboard.mailbox_detail_route",
                    mailbox_id=mailbox.id,
                )
            )

    return render_template(
        "dashboard/mailbox.html",
        mailboxes=mailboxes,
        new_mailbox_form=new_mailbox_form,
        delete_mailbox_form=delete_mailbox_form,
        csrf_form=csrf_form,
    )


@dashboard_bp.route("/mailbox_verify")
@login_required
def mailbox_verify():
    mailbox_id = request.args.get("mailbox_id")
    if not mailbox_id:
        LOG.i("Missing mailbox_id")
        flash("You followed an invalid link", "error")
        return redirect(url_for("dashboard.mailbox_route"))

    code = request.args.get("code")
    if not code:
        # Old way
        return verify_with_signed_secret(mailbox_id)

    try:
        mailbox = mailbox_utils.verify_mailbox_code(current_user, mailbox_id, code)
    except mailbox_utils.MailboxError as e:
        LOG.i(f"Cannot verify mailbox {mailbox_id} because of {e}")
        flash(f"Cannot verify mailbox: {e.msg}", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    LOG.d("Mailbox %s is verified", mailbox)
    return render_template("dashboard/mailbox_validation.html", mailbox=mailbox)


def verify_with_signed_secret(request: str):
    s = TimestampSigner(MAILBOX_SECRET)
    mailbox_verify_request = request.args.get("mailbox_id")
    try:
        mailbox_raw_data = s.unsign(mailbox_verify_request, max_age=900)
    except Exception:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    try:
        decoded_data = base64.urlsafe_b64decode(mailbox_raw_data)
    except binascii.Error:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    mailbox_data = json.loads(decoded_data)
    if not isinstance(mailbox_data, list) or len(mailbox_data) != 2:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    mailbox_id = mailbox_data[0]
    mailbox: Optional[Mailbox] = Mailbox.get(mailbox_id)
    if not mailbox:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    mailbox_email = mailbox_data[1]
    if mailbox_email != mailbox.email:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.mailbox_route"))

    mailbox.verified = True
    emit_user_audit_log(
        user=current_user,
        action=UserAuditLogAction.VerifyMailbox,
        message=f"Verified mailbox {mailbox.id} ({mailbox.email})",
    )
    Session.commit()

    LOG.d("Mailbox %s is verified", mailbox)

    return render_template("dashboard/mailbox_validation.html", mailbox=mailbox)
