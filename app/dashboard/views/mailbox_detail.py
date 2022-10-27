from smtplib import SMTPRecipientsRefused

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import Signer
from wtforms import validators
from wtforms.fields.html5 import EmailField

from app.config import ENFORCE_SPF, MAILBOX_SECRET
from app.config import URL
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.email_utils import email_can_be_used_as_mailbox
from app.email_utils import mailbox_already_used, render, send_email
from app.log import LOG
from app.models import Alias, AuthorizedAddress
from app.models import Mailbox
from app.pgp_utils import PGPException, load_public_key_and_check
from app.utils import sanitize_email, CSRFValidationForm


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
    csrf_form = CSRFValidationForm()

    if mailbox.new_email:
        pending_email = mailbox.new_email
    else:
        pending_email = None

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if (
            request.form.get("form-name") == "update-email"
            and change_email_form.validate_on_submit()
        ):
            new_email = sanitize_email(change_email_form.email.data)
            if new_email != mailbox.email and not pending_email:
                # check if this email is not already used
                if mailbox_already_used(new_email, current_user) or Alias.get_by(
                    email=new_email
                ):
                    flash(f"Email {new_email} already used", "error")
                elif not email_can_be_used_as_mailbox(new_email):
                    flash("You cannot use this email address as your mailbox", "error")
                else:
                    mailbox.new_email = new_email
                    Session.commit()

                    try:
                        verify_mailbox_change(current_user, mailbox, new_email)
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
        elif request.form.get("form-name") == "force-spf":
            if not ENFORCE_SPF:
                flash("SPF enforcement globally not enabled", "error")
                return redirect(url_for("dashboard.index"))

            mailbox.force_spf = (
                True if request.form.get("spf-status") == "on" else False
            )
            Session.commit()
            flash(
                "SPF enforcement was " + "enabled"
                if request.form.get("spf-status")
                else "disabled" + " successfully",
                "success",
            )
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
            )
        elif request.form.get("form-name") == "add-authorized-address":
            address = sanitize_email(request.form.get("email"))
            if AuthorizedAddress.get_by(mailbox_id=mailbox.id, email=address):
                flash(f"{address} already added", "error")
            else:
                AuthorizedAddress.create(
                    user_id=current_user.id,
                    mailbox_id=mailbox.id,
                    email=address,
                    commit=True,
                )
                flash(f"{address} added as authorized address", "success")

            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
            )
        elif request.form.get("form-name") == "delete-authorized-address":
            authorized_address_id = request.form.get("authorized-address-id")
            authorized_address: AuthorizedAddress = AuthorizedAddress.get(
                authorized_address_id
            )
            if not authorized_address or authorized_address.mailbox_id != mailbox.id:
                flash("Unknown error. Refresh the page", "warning")
            else:
                address = authorized_address.email
                AuthorizedAddress.delete(authorized_address_id)
                Session.commit()
                flash(f"{address} has been deleted", "success")

            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
            )
        elif request.form.get("form-name") == "pgp":
            if request.form.get("action") == "save":
                if not current_user.is_premium():
                    flash("Only premium plan can add PGP Key", "warning")
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )

                mailbox.pgp_public_key = request.form.get("pgp")
                try:
                    mailbox.pgp_finger_print = load_public_key_and_check(
                        mailbox.pgp_public_key
                    )
                except PGPException:
                    flash("Cannot add the public key, please verify it", "error")
                else:
                    Session.commit()
                    flash("Your PGP public key is saved successfully", "success")
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )
            elif request.form.get("action") == "remove":
                # Free user can decide to remove their added PGP key
                mailbox.pgp_public_key = None
                mailbox.pgp_finger_print = None
                mailbox.disable_pgp = False
                Session.commit()
                flash("Your PGP public key is removed successfully", "success")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                )

        elif request.form.get("form-name") == "toggle-pgp":
            if request.form.get("pgp-enabled") == "on":
                mailbox.disable_pgp = False
                flash(f"PGP is enabled on {mailbox.email}", "success")
            else:
                mailbox.disable_pgp = True
                flash(f"PGP is disabled on {mailbox.email}", "info")

            Session.commit()
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
            )
        elif request.form.get("form-name") == "generic-subject":
            if request.form.get("action") == "save":
                if not mailbox.pgp_enabled():
                    flash(
                        "Generic subject can only be used on PGP-enabled mailbox",
                        "error",
                    )
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )

                mailbox.generic_subject = request.form.get("generic-subject")
                Session.commit()
                flash("Generic subject for PGP-encrypted email is enabled", "success")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                )
            elif request.form.get("action") == "remove":
                mailbox.generic_subject = None
                Session.commit()
                flash("Generic subject for PGP-encrypted email is disabled", "success")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                )

    spf_available = ENFORCE_SPF
    return render_template("dashboard/mailbox_detail.html", **locals())


def verify_mailbox_change(user, mailbox, new_email):
    s = Signer(MAILBOX_SECRET)
    mailbox_id_signed = s.sign(str(mailbox.id)).decode()
    verification_url = (
        f"{URL}/dashboard/mailbox/confirm_change?mailbox_id={mailbox_id_signed}"
    )

    send_email(
        new_email,
        "Confirm mailbox change on SimpleLogin",
        render(
            "transactional/verify-mailbox-change.txt.jinja2",
            user=user,
            link=verification_url,
            mailbox_email=mailbox.email,
            mailbox_new_email=new_email,
        ),
        render(
            "transactional/verify-mailbox-change.html",
            user=user,
            link=verification_url,
            mailbox_email=mailbox.email,
            mailbox_new_email=new_email,
        ),
    )


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
        Session.commit()
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
    signed_mailbox_id = request.args.get("mailbox_id")

    try:
        mailbox_id = int(s.unsign(signed_mailbox_id))
    except Exception:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.index"))
    else:
        mailbox = Mailbox.get(mailbox_id)

        # new_email can be None if user cancels change in the meantime
        if mailbox and mailbox.new_email:
            user = mailbox.user
            if Mailbox.get_by(email=mailbox.new_email, user_id=user.id):
                flash(f"{mailbox.new_email} is already used", "error")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox.id)
                )

            mailbox.email = mailbox.new_email
            mailbox.new_email = None

            # mark mailbox as verified if the change request is sent from an unverified mailbox
            mailbox.verified = True
            Session.commit()

            LOG.d("Mailbox change %s is verified", mailbox)
            flash(f"The {mailbox.email} is updated", "success")
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox.id)
            )
        else:
            flash("Invalid link", "error")
            return redirect(url_for("dashboard.index"))
