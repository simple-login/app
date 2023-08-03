import base64
import binascii
import json

import arrow
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import TimestampSigner
from wtforms import validators, IntegerField
from wtforms.fields.html5 import EmailField

from app import parallel_limiter
from app.config import MAILBOX_SECRET, URL, JOB_DELETE_MAILBOX
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.email_utils import (
    email_can_be_used_as_mailbox,
    mailbox_already_used,
    render,
    send_email,
)
from app.email_validation import is_valid_email
from app.log import LOG
from app.models import Mailbox, Job
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

            if not mailbox or mailbox.user_id != current_user.id:
                flash("Invalid mailbox. Refresh the page", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if mailbox.id == current_user.default_mailbox_id:
                flash("You cannot delete default mailbox", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            transfer_mailbox_id = delete_mailbox_form.transfer_mailbox_id.data
            if transfer_mailbox_id and transfer_mailbox_id > 0:
                transfer_mailbox = Mailbox.get(transfer_mailbox_id)

                if not transfer_mailbox or transfer_mailbox.user_id != current_user.id:
                    flash(
                        "You must transfer the aliases to a mailbox you own.", "error"
                    )
                    return redirect(url_for("dashboard.mailbox_route"))

                if transfer_mailbox.id == mailbox.id:
                    flash(
                        "You can not transfer the aliases to the mailbox you want to delete.",
                        "error",
                    )
                    return redirect(url_for("dashboard.mailbox_route"))

                if not transfer_mailbox.verified:
                    flash("Your new mailbox is not verified", "error")
                    return redirect(url_for("dashboard.mailbox_route"))

            # Schedule delete account job
            LOG.w(
                f"schedule delete mailbox job for {mailbox.id} with transfer to mailbox {transfer_mailbox_id}"
            )
            Job.create(
                name=JOB_DELETE_MAILBOX,
                payload={
                    "mailbox_id": mailbox.id,
                    "transfer_mailbox_id": transfer_mailbox_id
                    if transfer_mailbox_id > 0
                    else None,
                },
                run_at=arrow.now(),
                commit=True,
            )

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

            if not mailbox or mailbox.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if mailbox.id == current_user.default_mailbox_id:
                flash("This mailbox is already default one", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            if not mailbox.verified:
                flash("Cannot set unverified mailbox as default", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            current_user.default_mailbox_id = mailbox.id
            Session.commit()
            flash(f"Mailbox {mailbox.email} is set as Default Mailbox", "success")

            return redirect(url_for("dashboard.mailbox_route"))

        elif request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add additional mailbox", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if new_mailbox_form.validate():
                mailbox_email = (
                    new_mailbox_form.email.data.lower().strip().replace(" ", "")
                )

                if not is_valid_email(mailbox_email):
                    flash(f"{mailbox_email} invalid", "error")
                elif mailbox_already_used(mailbox_email, current_user):
                    flash(f"{mailbox_email} already used", "error")
                elif not email_can_be_used_as_mailbox(mailbox_email):
                    flash(f"You cannot use {mailbox_email}.", "error")
                else:
                    new_mailbox = Mailbox.create(
                        email=mailbox_email, user_id=current_user.id
                    )
                    Session.commit()

                    send_verification_email(current_user, new_mailbox)

                    flash(
                        f"You are going to receive an email to confirm {mailbox_email}.",
                        "success",
                    )

                    return redirect(
                        url_for(
                            "dashboard.mailbox_detail_route",
                            mailbox_id=new_mailbox.id,
                        )
                    )

    return render_template(
        "dashboard/mailbox.html",
        mailboxes=mailboxes,
        new_mailbox_form=new_mailbox_form,
        delete_mailbox_form=delete_mailbox_form,
        csrf_form=csrf_form,
    )


def send_verification_email(user, mailbox):
    s = TimestampSigner(MAILBOX_SECRET)
    encoded_data = json.dumps([mailbox.id, mailbox.email]).encode("utf-8")
    b64_data = base64.urlsafe_b64encode(encoded_data)
    mailbox_id_signed = s.sign(b64_data).decode()
    verification_url = (
        URL + "/dashboard/mailbox_verify" + f"?mailbox_id={mailbox_id_signed}"
    )
    send_email(
        mailbox.email,
        f"Please confirm your mailbox {mailbox.email}",
        render(
            "transactional/verify-mailbox.txt.jinja2",
            user=user,
            link=verification_url,
            mailbox_email=mailbox.email,
        ),
        render(
            "transactional/verify-mailbox.html",
            user=user,
            link=verification_url,
            mailbox_email=mailbox.email,
        ),
    )


@dashboard_bp.route("/mailbox_verify")
def mailbox_verify():
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
    mailbox = Mailbox.get(mailbox_id)
    if not mailbox:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    mailbox_email = mailbox_data[1]
    if mailbox_email != mailbox.email:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.mailbox_route"))

    mailbox.verified = True
    Session.commit()

    LOG.d("Mailbox %s is verified", mailbox)

    return render_template("dashboard/mailbox_validation.html", mailbox=mailbox)
