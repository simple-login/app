import secrets
from typing import Optional

import arrow
from flask import (
    render_template,
    request,
    redirect,
    url_for,
    flash,
)
from flask_login import login_required, current_user

from app import email_utils
from app.config import (
    URL,
    FIRST_ALIAS_DOMAIN,
    ALIAS_RANDOM_SUFFIX_LENGTH,
    CONNECT_WITH_PROTON,
)
from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.dashboard.views.mailbox_detail import ChangeEmailForm
from app.dashboard.views.setting import get_partner_subscription_and_name
from app.db import Session
from app.email_utils import (
    email_can_be_used_as_mailbox,
    personal_email_already_used,
)
from app.errors import ProtonPartnerNotSetUp
from app.extensions import limiter
from app.jobs.export_user_data_job import ExportUserDataJob
from app.log import LOG
from app.models import (
    BlockBehaviourEnum,
    PlanEnum,
    ResetPasswordCode,
    EmailChange,
    User,
    Alias,
    AliasGeneratorEnum,
    SenderFormatEnum,
    UnsubscribeBehaviourEnum,
    PartnerUser,
)
from app.proton.proton_partner import get_proton_partner
from app.proton.proton_unlink import (
    perform_proton_account_unlink,
    can_unlink_proton_account,
)
from app.utils import (
    random_string,
    CSRFValidationForm,
    canonicalize_email,
)


def get_proton_linked_account() -> Optional[str]:
    # Check if the current user has a partner_id
    try:
        proton_partner_id = get_proton_partner().id
    except ProtonPartnerNotSetUp:
        return None

    # It has. Retrieve the information for the PartnerUser
    proton_linked_account = PartnerUser.get_by(
        user_id=current_user.id, partner_id=proton_partner_id
    )
    if proton_linked_account is None:
        return None
    return proton_linked_account.partner_email


@dashboard_bp.route("/account_setting", methods=["GET", "POST"])
@login_required
@sudo_required
@limiter.limit("5/minute", methods=["POST"])
def account_setting():
    change_email_form = ChangeEmailForm()
    csrf_form = CSRFValidationForm()

    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        pending_email = email_change.new_email
    else:
        pending_email = None

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(url_for("dashboard.setting"))
        if request.form.get("form-name") == "update-email":
            if change_email_form.validate():
                # whether user can proceed with the email update
                new_email_valid = True
                new_email = canonicalize_email(change_email_form.email.data)
                if new_email != current_user.email and not pending_email:
                    # check if this email is not already used
                    if personal_email_already_used(new_email) or Alias.get_by(
                        email=new_email
                    ):
                        flash(f"Email {new_email} already used", "error")
                        new_email_valid = False
                    elif not email_can_be_used_as_mailbox(new_email):
                        flash(
                            "You cannot use this email address as your personal inbox.",
                            "error",
                        )
                        new_email_valid = False
                    # a pending email change with the same email exists from another user
                    elif EmailChange.get_by(new_email=new_email):
                        other_email_change: EmailChange = EmailChange.get_by(
                            new_email=new_email
                        )
                        LOG.w(
                            "Another user has a pending %s with the same email address. Current user:%s",
                            other_email_change,
                            current_user,
                        )

                        if other_email_change.is_expired():
                            LOG.d(
                                "delete the expired email change %s", other_email_change
                            )
                            EmailChange.delete(other_email_change.id)
                            Session.commit()
                        else:
                            flash(
                                "You cannot use this email address as your personal inbox.",
                                "error",
                            )
                            new_email_valid = False

                    if new_email_valid:
                        email_change = EmailChange.create(
                            user_id=current_user.id,
                            code=random_string(
                                60
                            ),  # todo: make sure the code is unique
                            new_email=new_email,
                        )
                        Session.commit()
                        send_change_email_confirmation(current_user, email_change)
                        flash(
                            "A confirmation email is on the way, please check your inbox",
                            "success",
                        )
                        return redirect(url_for("dashboard.account_setting"))
        elif request.form.get("form-name") == "change-password":
            flash(
                "You are going to receive an email containing instructions to change your password",
                "success",
            )
            send_reset_password_email(current_user)
            return redirect(url_for("dashboard.account_setting"))
        elif request.form.get("form-name") == "send-full-user-report":
            if ExportUserDataJob(current_user).store_job_in_db():
                flash(
                    "You will receive your SimpleLogin data via email shortly",
                    "success",
                )
            else:
                flash("An export of your data is currently in progress", "error")

    partner_sub = None
    partner_name = None

    partner_sub_name = get_partner_subscription_and_name(current_user.id)
    if partner_sub_name:
        partner_sub, partner_name = partner_sub_name

    proton_linked_account = get_proton_linked_account()

    return render_template(
        "dashboard/account_setting.html",
        csrf_form=csrf_form,
        PlanEnum=PlanEnum,
        SenderFormatEnum=SenderFormatEnum,
        BlockBehaviourEnum=BlockBehaviourEnum,
        change_email_form=change_email_form,
        pending_email=pending_email,
        AliasGeneratorEnum=AliasGeneratorEnum,
        UnsubscribeBehaviourEnum=UnsubscribeBehaviourEnum,
        partner_sub=partner_sub,
        partner_name=partner_name,
        FIRST_ALIAS_DOMAIN=FIRST_ALIAS_DOMAIN,
        ALIAS_RAND_SUFFIX_LENGTH=ALIAS_RANDOM_SUFFIX_LENGTH,
        connect_with_proton=CONNECT_WITH_PROTON,
        proton_linked_account=proton_linked_account,
        can_unlink_proton_account=can_unlink_proton_account(current_user),
    )


def send_reset_password_email(user):
    """
    generate a new ResetPasswordCode and send it over email to user
    """
    # the activation code is valid for 1h
    reset_password_code = ResetPasswordCode.create(
        user_id=user.id, code=secrets.token_urlsafe(32)
    )
    Session.commit()

    reset_password_link = f"{URL}/auth/reset_password?code={reset_password_code.code}"

    email_utils.send_reset_password_email(user, reset_password_link)


def send_change_email_confirmation(user: User, email_change: EmailChange):
    """
    send confirmation email to the new email address
    """

    link = f"{URL}/auth/change_email?code={email_change.code}"

    email_utils.send_change_email(user, email_change.new_email, link)


@dashboard_bp.route("/resend_email_change", methods=["GET", "POST"])
@limiter.limit("5/hour")
@login_required
@sudo_required
def resend_email_change():
    form = CSRFValidationForm()
    if not form.validate():
        flash("Invalid request. Please try again", "warning")
        return redirect(url_for("dashboard.setting"))
    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        # extend email change expiration
        email_change.expired = arrow.now().shift(hours=12)
        Session.commit()

        send_change_email_confirmation(current_user, email_change)
        flash("A confirmation email is on the way, please check your inbox", "success")
        return redirect(url_for("dashboard.account_setting"))
    else:
        flash(
            "You have no pending email change. Redirect back to Setting page", "warning"
        )
        return redirect(url_for("dashboard.account_setting"))


@dashboard_bp.route("/cancel_email_change", methods=["GET", "POST"])
@login_required
@sudo_required
def cancel_email_change():
    form = CSRFValidationForm()
    if not form.validate():
        flash("Invalid request. Please try again", "warning")
        return redirect(url_for("dashboard.setting"))
    email_change = EmailChange.get_by(user_id=current_user.id)
    if email_change:
        EmailChange.delete(email_change.id)
        Session.commit()
        flash("Your email change is cancelled", "success")
        return redirect(url_for("dashboard.account_setting"))
    else:
        flash(
            "You have no pending email change. Redirect back to Setting page", "warning"
        )
        return redirect(url_for("dashboard.account_setting"))


@dashboard_bp.route("/unlink_proton_account", methods=["POST"])
@login_required
@sudo_required
def unlink_proton_account():
    csrf_form = CSRFValidationForm()
    if not csrf_form.validate():
        flash("Invalid request", "warning")
        return redirect(url_for("dashboard.setting"))

    if not perform_proton_account_unlink(current_user):
        flash("Account cannot be unlinked", "warning")
    else:
        flash("Your Proton account has been unlinked", "success")
    return redirect(url_for("dashboard.account_setting"))
