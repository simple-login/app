import arrow
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import Signer
from wtforms import validators
from wtforms.fields.html5 import EmailField

from app.config import MAILBOX_SECRET, URL, JOB_DELETE_MAILBOX
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.email_utils import (
    email_can_be_used_as_mailbox,
    mailbox_already_used,
    render,
    send_email,
    is_valid_email,
)
from app.log import LOG
from app.models import Mailbox, Job
from app.utils import CSRFValidationForm


class NewMailboxForm(FlaskForm):
    email = EmailField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


@dashboard_bp.route("/mailbox", methods=["GET", "POST"])
@login_required
def mailbox_route():
    mailboxes = (
        Mailbox.filter_by(user_id=current_user.id)
        .order_by(Mailbox.created_at.desc())
        .all()
    )

    new_mailbox_form = NewMailboxForm()
    csrf_form = CSRFValidationForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "delete":
            mailbox_id = request.form.get("mailbox-id")
            mailbox = Mailbox.get(mailbox_id)

            if not mailbox or mailbox.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if mailbox.id == current_user.default_mailbox_id:
                flash("You cannot delete default mailbox", "error")
                return redirect(url_for("dashboard.mailbox_route"))

            # Schedule delete account job
            LOG.w("schedule delete mailbox job for %s", mailbox)
            Job.create(
                name=JOB_DELETE_MAILBOX,
                payload={"mailbox_id": mailbox.id},
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
            mailbox_id = request.form.get("mailbox-id")
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
                            "dashboard.mailbox_detail_route", mailbox_id=new_mailbox.id
                        )
                    )

    return render_template(
        "dashboard/mailbox.html",
        mailboxes=mailboxes,
        new_mailbox_form=new_mailbox_form,
        csrf_form=csrf_form,
    )


def delete_mailbox(mailbox_id: int):
    from server import create_light_app

    with create_light_app().app_context():
        mailbox = Mailbox.get(mailbox_id)
        if not mailbox:
            return

        mailbox_email = mailbox.email
        user = mailbox.user

        Mailbox.delete(mailbox_id)
        Session.commit()
        LOG.d("Mailbox %s %s deleted", mailbox_id, mailbox_email)

        send_email(
            user.email,
            f"Your mailbox {mailbox_email} has been deleted",
            f"""Mailbox {mailbox_email} along with its aliases are deleted successfully.

Regards,
SimpleLogin team.
        """,
        )


def send_verification_email(user, mailbox):
    s = Signer(MAILBOX_SECRET)
    mailbox_id_signed = s.sign(str(mailbox.id)).decode()
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
    s = Signer(MAILBOX_SECRET)
    mailbox_id = request.args.get("mailbox_id")

    try:
        r_id = int(s.unsign(mailbox_id))
    except Exception:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
        return redirect(url_for("dashboard.mailbox_route"))
    else:
        mailbox = Mailbox.get(r_id)
        if not mailbox:
            flash("Invalid link", "error")
            return redirect(url_for("dashboard.mailbox_route"))

        mailbox.verified = True
        Session.commit()

        LOG.d("Mailbox %s is verified", mailbox)

        return render_template("dashboard/mailbox_validation.html", mailbox=mailbox)
