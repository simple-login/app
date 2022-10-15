from typing import Optional

import arrow
import sqlalchemy
from flask_admin.model.template import EndpointLinkRowAction
from markupsafe import Markup

from app import models, s3
from flask import redirect, url_for, request, flash, Response
from flask_admin import expose, AdminIndexView
from flask_admin.actions import action
from flask_admin.contrib import sqla
from flask_login import current_user

from app.db import Session
from app.models import (
    User,
    ManualSubscription,
    Fido,
    Subscription,
    AppleSubscription,
    AdminAuditLog,
    AuditLogActionEnum,
    ProviderComplaintState,
    Phase,
    ProviderComplaint,
    Alias,
    Newsletter,
    PADDLE_SUBSCRIPTION_GRACE_DAYS,
)
from app.newsletter_utils import send_newsletter_to_user, send_newsletter_to_address


class SLModelView(sqla.ModelView):
    column_default_sort = ("id", True)
    column_display_pk = True

    can_edit = False
    can_create = False
    can_delete = False
    edit_modal = True

    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        return redirect(url_for("auth.login", next=request.url))

    def on_model_change(self, form, model, is_created):
        changes = {}
        for attr in sqlalchemy.inspect(model).attrs:
            if attr.history.has_changes() and attr.key not in (
                "created_at",
                "updated_at",
            ):
                value = attr.value
                # If it's a model reference, get the source id
                if issubclass(type(value), models.Base):
                    value = value.id
                # otherwise, if its a generic object stringify it
                if issubclass(type(value), object):
                    value = str(value)
                changes[attr.key] = value
        auditAction = (
            AuditLogActionEnum.create_object
            if is_created
            else AuditLogActionEnum.update_object
        )
        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model=model.__class__.__name__,
            model_id=model.id,
            action=auditAction.value,
            data=changes,
        )

    def on_model_delete(self, model):
        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model=model.__class__.__name__,
            model_id=model.id,
            action=AuditLogActionEnum.delete_object.value,
        )


class SLAdminIndexView(AdminIndexView):
    @expose("/")
    def index(self):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login", next=request.url))

        return redirect("/admin/user")


def _user_upgrade_channel_formatter(view, context, model, name):
    return Markup(model.upgrade_channel)


class UserAdmin(SLModelView):
    column_searchable_list = ["email", "id"]
    column_exclude_list = [
        "salt",
        "password",
        "otp_secret",
        "last_otp",
        "fido_uuid",
        "profile_picture",
    ]
    can_edit = False

    def scaffold_list_columns(self):
        ret = super().scaffold_list_columns()
        ret.insert(0, "upgrade_channel")
        return ret

    column_formatters = {
        "upgrade_channel": _user_upgrade_channel_formatter,
    }

    @action(
        "education_upgrade",
        "Education upgrade",
        "Are you sure you want to edu-upgrade selected users?",
    )
    def action_edu_upgrade(self, ids):
        manual_upgrade("Edu", ids, is_giveaway=True)

    @action(
        "charity_org_upgrade",
        "Charity Organization upgrade",
        "Are you sure you want to upgrade selected users using the Charity organization program?",
    )
    def action_charity_org_upgrade(self, ids):
        manual_upgrade("Charity Organization", ids, is_giveaway=True)

    @action(
        "journalist_upgrade",
        "Journalist upgrade",
        "Are you sure you want to upgrade selected users using the Journalist program?",
    )
    def action_journalist_upgrade(self, ids):
        manual_upgrade("Journalist", ids, is_giveaway=True)

    @action(
        "cash_upgrade",
        "Cash upgrade",
        "Are you sure you want to cash-upgrade selected users?",
    )
    def action_cash_upgrade(self, ids):
        manual_upgrade("Cash", ids, is_giveaway=False)

    @action(
        "crypto_upgrade",
        "Crypto upgrade",
        "Are you sure you want to crypto-upgrade selected users?",
    )
    def action_monero_upgrade(self, ids):
        manual_upgrade("Crypto", ids, is_giveaway=False)

    @action(
        "adhoc_upgrade",
        "Adhoc upgrade - for exceptional case",
        "Are you sure you want to crypto-upgrade selected users?",
    )
    def action_adhoc_upgrade(self, ids):
        manual_upgrade("Adhoc", ids, is_giveaway=False)

    @action(
        "extend_trial_1w",
        "Extend trial for 1 week more",
        "Extend trial for 1 week more?",
    )
    def extend_trial_1w(self, ids):
        for user in User.filter(User.id.in_(ids)):
            if user.trial_end and user.trial_end > arrow.now():
                user.trial_end = user.trial_end.shift(weeks=1)
            else:
                user.trial_end = arrow.now().shift(weeks=1)

            flash(f"Extend trial for {user} to {user.trial_end}", "success")
            AdminAuditLog.extend_trial(
                current_user.id, user.id, user.trial_end, "1 week"
            )

        Session.commit()

    @action(
        "disable_otp_fido",
        "Disable OTP & FIDO",
        "Disable OTP & FIDO?",
    )
    def disable_otp_fido(self, ids):
        for user in User.filter(User.id.in_(ids)):
            user_had_otp = user.enable_otp
            if user.enable_otp:
                user.enable_otp = False
                flash(f"Disable OTP for {user}", "info")

            user_had_fido = user.fido_uuid is not None
            if user.fido_uuid:
                Fido.filter_by(uuid=user.fido_uuid).delete()
                user.fido_uuid = None
                flash(f"Disable FIDO for {user}", "info")
            AdminAuditLog.disable_otp_fido(
                current_user.id, user.id, user_had_otp, user_had_fido
            )

        Session.commit()

    @action(
        "stop_paddle_sub",
        "Stop user Paddle subscription",
        "This will stop the current user Paddle subscription so if user doesn't have Proton sub, they will lose all SL benefits immediately",
    )
    def stop_paddle_sub(self, ids):
        for user in User.filter(User.id.in_(ids)):
            sub: Subscription = user.get_paddle_subscription()
            if not sub:
                flash(f"No Paddle sub for {user}", "warning")
                continue

            flash(f"{user} sub will end now, instead of {sub.next_bill_date}", "info")
            sub.next_bill_date = (
                arrow.now().shift(days=-PADDLE_SUBSCRIPTION_GRACE_DAYS).date()
            )

        Session.commit()

    # @action(
    #     "login_as",
    #     "Login as this user",
    #     "Login as this user?",
    # )
    # def login_as(self, ids):
    #     if len(ids) != 1:
    #         flash("only 1 user can be selected", "error")
    #         return
    #
    #     for user in User.filter(User.id.in_(ids)):
    #         AdminAuditLog.logged_as_user(current_user.id, user.id)
    #         login_user(user)
    #         flash(f"Login as user {user}", "success")
    #         return redirect("/")


def manual_upgrade(way: str, ids: [int], is_giveaway: bool):
    for user in User.filter(User.id.in_(ids)).all():
        if user.lifetime:
            flash(f"user {user} already has a lifetime license", "warning")
            continue

        sub: Subscription = user.get_paddle_subscription()
        if sub and not sub.cancelled:
            flash(
                f"user {user} already has a Paddle license, they have to cancel it first",
                "warning",
            )
            continue

        apple_sub: AppleSubscription = AppleSubscription.get_by(user_id=user.id)
        if apple_sub and apple_sub.is_valid():
            flash(
                f"user {user} already has a Apple subscription, they have to cancel it first",
                "warning",
            )
            continue

        AdminAuditLog.create_manual_upgrade(current_user.id, way, user.id, is_giveaway)
        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=user.id)
        if manual_sub:
            # renew existing subscription
            if manual_sub.end_at > arrow.now():
                manual_sub.end_at = manual_sub.end_at.shift(years=1)
            else:
                manual_sub.end_at = arrow.now().shift(years=1, days=1)
            flash(f"Subscription extended to {manual_sub.end_at.humanize()}", "success")
            continue

        ManualSubscription.create(
            user_id=user.id,
            end_at=arrow.now().shift(years=1, days=1),
            comment=way,
            is_giveaway=is_giveaway,
        )

        flash(f"New {way} manual subscription for {user} is created", "success")
    Session.commit()


class EmailLogAdmin(SLModelView):
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "mailbox.email", "contact.website_email"]

    can_edit = False
    can_create = False


class AliasAdmin(SLModelView):
    column_searchable_list = ["id", "user.email", "email", "mailbox.email"]
    column_filters = ["id", "user.email", "email", "mailbox.email"]

    @action(
        "disable_email_spoofing_check",
        "Disable email spoofing protection",
        "Disable email spoofing protection?",
    )
    def disable_email_spoofing_check_for(self, ids):
        for alias in Alias.filter(Alias.id.in_(ids)):
            if alias.disable_email_spoofing_check:
                flash(
                    f"Email spoofing protection is already disabled on {alias.email}",
                    "warning",
                )
            else:
                alias.disable_email_spoofing_check = True
                flash(
                    f"Email spoofing protection is disabled on {alias.email}", "success"
                )

        Session.commit()


class MailboxAdmin(SLModelView):
    column_searchable_list = ["id", "user.email", "email"]
    column_filters = ["id", "user.email", "email"]


# class LifetimeCouponAdmin(SLModelView):
#     can_edit = True
#     can_create = True


class CouponAdmin(SLModelView):
    can_edit = False
    can_create = True


class ManualSubscriptionAdmin(SLModelView):
    can_edit = True
    column_searchable_list = ["id", "user.email"]

    @action(
        "extend_1y",
        "Extend for 1 year",
        "Extend 1 year more?",
    )
    def extend_1y(self, ids):
        for ms in ManualSubscription.filter(ManualSubscription.id.in_(ids)):
            ms.end_at = ms.end_at.shift(years=1)
            flash(f"Extend subscription for 1 year for {ms.user}", "success")
            AdminAuditLog.extend_subscription(
                current_user.id, ms.user.id, ms.end_at, "1 year"
            )

        Session.commit()

    @action(
        "extend_1m",
        "Extend for 1 month",
        "Extend 1 month more?",
    )
    def extend_1m(self, ids):
        for ms in ManualSubscription.filter(ManualSubscription.id.in_(ids)):
            ms.end_at = ms.end_at.shift(months=1)
            flash(f"Extend subscription for 1 month for {ms.user}", "success")
            AdminAuditLog.extend_subscription(
                current_user.id, ms.user.id, ms.end_at, "1 month"
            )

        Session.commit()


# class ClientAdmin(SLModelView):
#     column_searchable_list = ["name", "description", "user.email"]
#     column_exclude_list = ["oauth_client_secret", "home_url"]
#     can_edit = True


class CustomDomainAdmin(SLModelView):
    column_searchable_list = ["domain", "user.email", "user.id"]
    column_exclude_list = ["ownership_txt_token"]
    can_edit = False


class ReferralAdmin(SLModelView):
    column_searchable_list = ["id", "user.email", "code", "name"]
    column_filters = ["id", "user.email", "code", "name"]

    def scaffold_list_columns(self):
        ret = super().scaffold_list_columns()
        ret.insert(0, "nb_user")
        ret.insert(0, "nb_paid_user")
        return ret


# class PayoutAdmin(SLModelView):
#     column_searchable_list = ["id", "user.email"]
#     column_filters = ["id", "user.email"]
#     can_edit = True
#     can_create = True
#     can_delete = True


def _admin_action_formatter(view, context, model, name):
    action_name = AuditLogActionEnum.get_name(model.action)
    return "{} ({})".format(action_name, model.action)


def _admin_created_at_formatter(view, context, model, name):
    return model.created_at.format()


class AdminAuditLogAdmin(SLModelView):
    column_searchable_list = ["admin.id", "admin.email", "model_id", "created_at"]
    column_filters = ["admin.id", "admin.email", "model_id", "created_at"]
    column_exclude_list = ["id"]
    column_hide_backrefs = False
    can_edit = False
    can_create = False
    can_delete = False

    column_formatters = {
        "action": _admin_action_formatter,
        "created_at": _admin_created_at_formatter,
    }


def _transactionalcomplaint_state_formatter(view, context, model, name):
    return "{} ({})".format(ProviderComplaintState(model.state).name, model.state)


def _transactionalcomplaint_phase_formatter(view, context, model, name):
    return Phase(model.phase).name


def _transactionalcomplaint_refused_email_id_formatter(view, context, model, name):
    markupstring = "<a href='{}'>{}</a>".format(
        url_for(".download_eml", id=model.id), model.refused_email.full_report_path
    )
    return Markup(markupstring)


class ProviderComplaintAdmin(SLModelView):
    column_searchable_list = ["id", "user.id", "created_at"]
    column_filters = ["user.id", "state"]
    column_hide_backrefs = False
    can_edit = False
    can_create = False
    can_delete = False

    column_formatters = {
        "created_at": _admin_created_at_formatter,
        "updated_at": _admin_created_at_formatter,
        "state": _transactionalcomplaint_state_formatter,
        "phase": _transactionalcomplaint_phase_formatter,
        "refused_email": _transactionalcomplaint_refused_email_id_formatter,
    }

    column_extra_row_actions = [  # Add a new action button
        EndpointLinkRowAction("fa fa-check-square", ".mark_ok"),
    ]

    def _get_complaint(self) -> Optional[ProviderComplaint]:
        complain_id = request.args.get("id")
        if complain_id is None:
            flash("Missing id", "error")
            return None
        complaint = ProviderComplaint.get_by(id=complain_id)
        if not complaint:
            flash("Could not find complaint", "error")
            return None
        return complaint

    @expose("/mark_ok", methods=["GET"])
    def mark_ok(self):
        complaint = self._get_complaint()
        if not complaint:
            return redirect("/admin/transactionalcomplaint/")
        complaint.state = ProviderComplaintState.reviewed.value
        Session.commit()
        return redirect("/admin/transactionalcomplaint/")

    @expose("/download_eml", methods=["GET"])
    def download_eml(self):
        complaint = self._get_complaint()
        if not complaint:
            return redirect("/admin/transactionalcomplaint/")
        eml_path = complaint.refused_email.full_report_path
        eml_data = s3.download_email(eml_path)
        AdminAuditLog.downloaded_provider_complaint(current_user.id, complaint.id)
        Session.commit()
        return Response(
            eml_data,
            mimetype="message/rfc822",
            headers={
                "Content-Disposition": "attachment;filename={}".format(
                    complaint.refused_email.path
                )
            },
        )


def _newsletter_plain_text_formatter(view, context, model: Newsletter, name):
    # to display newsletter plain_text with linebreaks in the list view
    return Markup(model.plain_text.replace("\n", "<br>"))


def _newsletter_html_formatter(view, context, model: Newsletter, name):
    # to display newsletter html with linebreaks in the list view
    return Markup(model.html.replace("\n", "<br>"))


class NewsletterAdmin(SLModelView):
    list_template = "admin/model/newsletter-list.html"
    edit_template = "admin/model/newsletter-edit.html"
    edit_modal = False

    can_edit = True
    can_create = True

    column_formatters = {
        "plain_text": _newsletter_plain_text_formatter,
        "html": _newsletter_html_formatter,
    }

    @action(
        "send_newsletter_to_user",
        "Send this newsletter to myself or the specified userID",
    )
    def send_newsletter_to_user(self, newsletter_ids):
        user_id = request.form["user_id"]
        if user_id:
            user = User.get(user_id)
            if not user:
                flash(f"No such user with ID {user_id}", "error")
                return
        else:
            flash("use the current user", "info")
            user = current_user

        for newsletter_id in newsletter_ids:
            newsletter = Newsletter.get(newsletter_id)
            sent, error_msg = send_newsletter_to_user(newsletter, user)
            if sent:
                flash(f"{newsletter} sent to {user}", "success")
            else:
                flash(error_msg, "error")

    @action(
        "send_newsletter_to_address",
        "Send this newsletter to a specific address",
    )
    def send_newsletter_to_address(self, newsletter_ids):
        to_address = request.form["to_address"]
        if not to_address:
            flash("to_address missing", "error")
            return

        for newsletter_id in newsletter_ids:
            newsletter = Newsletter.get(newsletter_id)
            # use the current_user for rendering email
            sent, error_msg = send_newsletter_to_address(
                newsletter, current_user, to_address
            )
            if sent:
                flash(
                    f"{newsletter} sent to {to_address} with {current_user} context",
                    "success",
                )
            else:
                flash(error_msg, "error")


class NewsletterUserAdmin(SLModelView):
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "newsletter.subject"]
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_edit = False
    can_create = False


class DailyMetricAdmin(SLModelView):
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_export = True


class MetricAdmin(SLModelView):
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_export = True
