from email_validator import validate_email, EmailNotValidError
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import TimestampSigner
from wtforms import validators
from wtforms.fields.simple import StringField

from app import mailbox_utils
from app.config import ENFORCE_SPF, MAILBOX_SECRET
from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.extensions import limiter
from app.mailbox_utils import (
    perform_mailbox_email_change,
    MailboxEmailChangeError,
    MailboxError,
)
from app.models import AuthorizedAddress
from app.models import Mailbox
from app.pgp_utils import PGPException, load_public_key_and_check, create_pgp_context
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.utils import sanitize_email, CSRFValidationForm


class ChangeEmailForm(FlaskForm):
    email = StringField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


@dashboard_bp.route("/mailbox/<int:mailbox_id>/", methods=["GET", "POST"])
@login_required
@sudo_required
@limiter.limit("20/minute", methods=["POST"])
def mailbox_detail_route(mailbox_id):
    mailbox: Mailbox = Mailbox.get(mailbox_id)
    if not mailbox or mailbox.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if mailbox.is_admin_disabled():
        flash("You cannot modify that mailbox. Please contact support.", "error")
        return redirect(url_for("dashboard.mailbox_route"))

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
            try:
                response = mailbox_utils.request_mailbox_email_change(
                    current_user, mailbox, change_email_form.email.data
                )
                flash(
                    f"You are going to receive an email to confirm {mailbox.email}.",
                    "success",
                )
            except mailbox_utils.MailboxError as e:
                flash(e.msg, "error")
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
            )
        elif request.form.get("form-name") == "force-spf":
            if not ENFORCE_SPF:
                flash("SPF enforcement globally not enabled", "error")
                return redirect(url_for("dashboard.index"))

            force_spf_value = request.form.get("spf-status") == "on"
            mailbox.force_spf = force_spf_value
            emit_user_audit_log(
                user=current_user,
                action=UserAuditLogAction.UpdateMailbox,
                message=f"Set force_spf to {force_spf_value} on mailbox {mailbox_id} ({mailbox.email})",
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
            try:
                validate_email(
                    address, check_deliverability=False, allow_smtputf8=False
                ).domain
            except EmailNotValidError:
                flash(f"invalid {address}", "error")
            else:
                if AuthorizedAddress.get_by(mailbox_id=mailbox.id, email=address):
                    flash(f"{address} already added", "error")
                else:
                    emit_user_audit_log(
                        user=current_user,
                        action=UserAuditLogAction.UpdateMailbox,
                        message=f"Add authorized address {address} to mailbox {mailbox_id} ({mailbox.email})",
                    )
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
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateMailbox,
                    message=f"Remove authorized address {address} from mailbox {mailbox_id} ({mailbox.email})",
                )
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

                if mailbox.is_proton():
                    flash(
                        "Enabling PGP for a Proton Mail mailbox is redundant and does not add any security benefit",
                        "info",
                    )
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )

                mailbox.pgp_public_key = request.form.get("pgp")
                try:
                    mailbox.pgp_finger_print = load_public_key_and_check(
                        mailbox.pgp_public_key, create_pgp_context()
                    )
                except PGPException:
                    flash("Cannot add the public key, please verify it", "error")
                else:
                    emit_user_audit_log(
                        user=current_user,
                        action=UserAuditLogAction.UpdateMailbox,
                        message=f"Add PGP Key {mailbox.pgp_finger_print} to mailbox {mailbox_id} ({mailbox.email})",
                    )
                    Session.commit()
                    flash("Your PGP public key is saved successfully", "success")
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )
            elif request.form.get("action") == "remove":
                # Free user can decide to remove their added PGP key
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateMailbox,
                    message=f"Remove PGP Key {mailbox.pgp_finger_print} from mailbox {mailbox_id} ({mailbox.email})",
                )
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
                if mailbox.is_proton():
                    mailbox.disable_pgp = True
                    flash(
                        "Enabling PGP for a Proton Mail mailbox is redundant and does not add any security benefit",
                        "info",
                    )
                else:
                    mailbox.disable_pgp = False
                    emit_user_audit_log(
                        user=current_user,
                        action=UserAuditLogAction.UpdateMailbox,
                        message=f"Enabled PGP for mailbox {mailbox_id} ({mailbox.email})",
                    )
                    flash(f"PGP is enabled on {mailbox.email}", "info")
            else:
                mailbox.disable_pgp = True
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateMailbox,
                    message=f"Disabled PGP for mailbox {mailbox_id} ({mailbox.email})",
                )
                flash(f"PGP is disabled on {mailbox.email}", "info")

            Session.commit()
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
            )
        elif request.form.get("form-name") == "generic-subject":
            if request.form.get("action") == "save":
                mailbox.generic_subject = request.form.get("generic-subject")
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateMailbox,
                    message=f"Set generic subject for mailbox {mailbox_id} ({mailbox.email})",
                )
                Session.commit()
                flash("Generic subject is enabled", "success")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                )
            elif request.form.get("action") == "remove":
                mailbox.generic_subject = None
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateMailbox,
                    message=f"Remove generic subject for mailbox {mailbox_id} ({mailbox.email})",
                )
                Session.commit()
                flash("Generic subject is disabled", "success")
                return redirect(
                    url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                )

    spf_available = ENFORCE_SPF
    return render_template("dashboard/mailbox_detail.html", **locals())


@dashboard_bp.route(
    "/mailbox/<int:mailbox_id>/cancel_email_change", methods=["GET", "POST"]
)
@login_required
def cancel_mailbox_change_route(mailbox_id):
    try:
        mailbox_utils.cancel_email_change(mailbox_id, current_user)
        flash("Your mailbox change is cancelled", "success")
        return redirect(
            url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
        )
    except MailboxError as e:
        flash(e.msg, "warning")
        return redirect(url_for("dashboard.index"))


@dashboard_bp.route("/mailbox/confirm_change")
@login_required
@limiter.limit("3/minute")
def mailbox_confirm_email_change_route():
    mailbox_id = request.args.get("mailbox_id")

    code = request.args.get("code")
    if code:
        try:
            mailbox = mailbox_utils.verify_mailbox_code(current_user, mailbox_id, code)
            flash("Successfully changed mailbox email", "success")
            return redirect(
                url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox.id)
            )
        except mailbox_utils.MailboxError as e:
            flash(f"Cannot verify mailbox: {e.msg}", "error")
            return redirect(url_for("dashboard.mailbox_route"))
    else:
        s = TimestampSigner(MAILBOX_SECRET)
        try:
            mailbox_id = int(s.unsign(mailbox_id, max_age=900))
            res = perform_mailbox_email_change(mailbox_id)
            flash(res.message, res.message_category)
            if res.error:
                if res.error == MailboxEmailChangeError.EmailAlreadyUsed:
                    return redirect(
                        url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id)
                    )
                elif res.error == MailboxEmailChangeError.InvalidId:
                    return redirect(url_for("dashboard.index"))
                else:
                    raise Exception("Unhandled MailboxEmailChangeError")
        except Exception:
            flash("Invalid link", "error")
            return redirect(url_for("dashboard.index"))

    flash("Successfully changed mailbox email", "success")
    return redirect(url_for("dashboard.mailbox_detail_route", mailbox_id=mailbox_id))
