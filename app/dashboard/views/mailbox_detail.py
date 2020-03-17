from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import Signer, BadSignature
from wtforms import validators
from wtforms.fields.html5 import EmailField

from app.config import MAILBOX_SECRET
from app.config import URL
from app.dashboard.base import dashboard_bp
from app.email_utils import can_be_used_as_personal_email, email_already_used
from app.email_utils import mailbox_already_used, render, send_email
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, DeletedAlias
from app.models import Mailbox
from app.pgp_utils import PGPException, load_public_key
from smtplib import SMTPRecipientsRefused


class ChangeEmailForm(FlaskForm):
    email = EmailField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


@dashboard_bp.route("/mailbox/<int:mailbox_id>/", methods=["GET", "POST"])
@login_required
def mailbox_detail_route(mailbox_id):
    mailbox = Mailbox.get(mailbox_id)
    if not mailbox or mailbox.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    change_email_form = ChangeEmailForm()

    if mailbox.new_email:
        pending_email = mailbox.new_email
    else:
        pending_email = None

    if request.method == "POST":
        if (
            request.form.get("form-name") == "update-email"
            and change_email_form.validate_on_submit()
        ):
            new_email = change_email_form.email.data
            if new_email != mailbox.email and not pending_email:
                # check if this email is not already used
                if (
                    mailbox_already_used(new_email, current_user)
                    or GenEmail.get_by(email=new_email)
                    or DeletedAlias.get_by(email=new_email)
                ):
                    flash(f"Email {new_email} already used", "error")
                elif not can_be_used_as_personal_email(new_email):
                    flash("You cannot use this email address as your mailbox", "error")
                else:
                    mailbox.new_email = new_email
                    db.session.commit()

                    s = Signer(MAILBOX_SECRET)
                    mailbox_id_signed = s.sign(str(mailbox.id)).decode()
                    verification_url = (
                        URL
                        + "/dashboard/mailbox/confirm_change"
                        + f"?mailbox_id={mailbox_id_signed}"
                    )

                    try:
                        send_email(
                            new_email,
                            f"Confirm mailbox change on SimpleLogin",
                            render(
                                "transactional/verify-mailbox-change.txt",
                                user=current_user,
                                link=verification_url,
                                mailbox_email=mailbox.email,
                                mailbox_new_email=new_email,
                            ),
                            render(
                                "transactional/verify-mailbox-change.html",
                                user=current_user,
                                link=verification_url,
                                mailbox_email=mailbox.email,
                                mailbox_new_email=new_email,
                            ),
                        )
                    except SMTPRecipientsRefused:
                        flash(
                            f"Incorrect mailbox, please recheck {mailbox.email}",
                            "error",
                        )
                    else:
                        flash(
                            f"You are going to receive an email to confirm {new_email}.",
                            "success",
                        )
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )
        elif request.form.get("form-name") == "pgp":
            if request.form.get("action") == "save":
                mailbox.pgp_public_key = request.form.get("pgp")
                try:
                    mailbox.pgp_finger_print = load_public_key(mailbox.pgp_public_key)
                except PGPException:
                    flash("Cannot add the public key, please verify it", "error")
                else:
                    db.session.commit()
                    flash("Your PGP public key is saved successfully", "success")
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )
            elif request.form.get("action") == "remove":
                mailbox.pgp_public_key = None
                mailbox.pgp_finger_print = None
                db.session.commit()
                flash("Your PGP public key is removed successfully", "success")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                )

    return render_template("dashboard/mailbox_detail.html", **locals())


@dashboard_bp.route(
    "/mailbox/<int:mailbox_id>/cancel_email_change", methods=["GET", "POST"]
)
@login_required
def cancel_mailbox_change_route(mailbox_id):
    mailbox = Mailbox.get(mailbox_id)
    if not mailbox or mailbox.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if mailbox.new_email:
        mailbox.new_email = None
        db.session.commit()
        flash("Your mailbox change is cancelled", "success")
        return redirect(
            url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
        )
    else:
        flash("You have no pending mailbox change", "warning")
        return redirect(
            url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
        )


@dashboard_bp.route("/mailbox/confirm_change")
def mailbox_confirm_change_route():
    s = Signer(MAILBOX_SECRET)
    mailbox_id = request.args.get("mailbox_id")

    try:
        r_id = int(s.unsign(mailbox_id))
    except Exception:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.index"))
    else:
        mailbox = Mailbox.get(r_id)

        # new_email can be None if user cancels change in the meantime
        if mailbox and mailbox.new_email:
            mailbox.email = mailbox.new_email
            mailbox.new_email = None

            # mark mailbox as verified if the change request is sent from an unverified mailbox
            mailbox.verified = True
            db.session.commit()

            LOG.d("Mailbox change %s is verified", mailbox)
            flash(f"The {mailbox.email} is updated", "success")
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox.id)
            )
        else:
            flash("Invalid link", "error")
            return redirect(url_for("dashboard.index"))
