from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import TimestampSigner
from wtforms import validators, IntegerField
from wtforms.fields.html5 import EmailField

from app import parallel_limiter
from app.config import MAILBOX_SECRET
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.mailbox_utils import (
    create_mailbox_and_send_verification,
    set_mailbox_verified,
    MailboxError,
    delete_mailbox,
)
from app.models import Mailbox
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
            try:
                mailbox = delete_mailbox(delete_mailbox_form.mailbox_id.data)
            except MailboxError as e:
                flash(str(e), "error")
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
            mailbox_email = new_mailbox_form.email.data.lower().strip().replace(" ", "")
            try:
                new_mailbox = create_mailbox_and_send_verification(
                    current_user, mailbox_email
                )
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
            except MailboxError as e:
                flash(str(e), "error")

    return render_template(
        "dashboard/mailbox.html",
        mailboxes=mailboxes,
        new_mailbox_form=new_mailbox_form,
        delete_mailbox_form=delete_mailbox_form,
        csrf_form=csrf_form,
    )


@dashboard_bp.route("/mailbox_verify")
def mailbox_verify():
    s = TimestampSigner(MAILBOX_SECRET)
    mailbox_id = request.args.get("mailbox_id")

    try:
        r_id = int(s.unsign(mailbox_id, max_age=900))
    except Exception:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    else:
        mailbox = Mailbox.get(r_id)
        if not mailbox:
            flash("Invalid link", "error")
            return redirect(url_for("dashboard.mailbox_route"))

        set_mailbox_verified(mailbox)

        LOG.d("Mailbox %s is verified", mailbox)

        return render_template("dashboard/mailbox_validation.html", mailbox=mailbox)
