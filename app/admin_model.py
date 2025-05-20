from __future__ import annotations

from typing import Optional, List, Dict

import arrow
import sqlalchemy
from flask import redirect, url_for, request, flash, Response
from flask_admin import BaseView
from flask_admin import expose, AdminIndexView
from flask_admin.actions import action
from flask_admin.contrib import sqla
from flask_admin.form import SecureForm
from flask_admin.model.template import EndpointLinkRowAction
from flask_login import current_user
from markupsafe import Markup

from app import models, s3, config
from app.abuser_utils import (
    mark_user_as_abuser,
    unmark_as_abusive_user,
    get_abuser_bundles_for_address,
)
from app.custom_domain_validation import (
    CustomDomainValidation,
    DomainValidationResult,
    ExpectedValidationRecords,
)
from app.db import Session
from app.dns_utils import get_network_dns_client
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
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
    Mailbox,
    DeletedAlias,
    DomainDeletedAlias,
    PartnerUser,
    AliasMailbox,
    AliasAuditLog,
    UserAuditLog,
    CustomDomain,
)
from app.newsletter_utils import send_newsletter_to_user, send_newsletter_to_address
from app.proton.proton_unlink import perform_proton_account_unlink
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
from app.utils import sanitize_email
from datetime import datetime
import json


def _admin_action_formatter(view, context, model, name):
    action_name = AuditLogActionEnum.get_name(model.action)
    return "{} ({})".format(action_name, model.action)


def _admin_date_formatter(view, context, model, name):
    return model.created_at.format()


def _user_upgrade_channel_formatter(view, context, model, name):
    return Markup(model.upgrade_channel)


class SLModelView(sqla.ModelView):
    column_default_sort = ("id", True)
    column_display_pk = True
    page_size = 100

    can_edit = False
    can_create = False
    can_delete = False
    edit_modal = True

    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

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

        return redirect(url_for("admin.email_search.index"))


class UserAdmin(SLModelView):
    form_base_class = SecureForm
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
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

    @action(
        "disable_user",
        "Disable user",
        "Are you sure you want to disable the selected users?",
    )
    def action_disable_user(self, ids):
        for user in User.filter(User.id.in_(ids)):
            mark_user_as_abuser(
                user, f"An user {user.id} was marked as abuser.", current_user.id
            )

            flash(f"Disabled user {user.id}")
            AdminAuditLog.disable_user(current_user.id, user.id)

        Session.commit()

    @action(
        "enable_user",
        "Enable user",
        "Are you sure you want to enable the selected users?",
    )
    def action_enable_user(self, ids):
        for user in User.filter(User.id.in_(ids)):
            unmark_as_abusive_user(
                user.id, f"An user {user.id} was unmarked as abuser.", current_user.id
            )

            flash(f"Enabled user {user.id}")
            AdminAuditLog.enable_user(current_user.id, user.id)

        Session.commit()

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
        "remove trial",
        "Stop trial period",
        "Remove trial for this user?",
    )
    def stop_trial(self, ids):
        for user in User.filter(User.id.in_(ids)):
            user.trial_end = None

            flash(f"Stopped trial for {user}", "success")
            AdminAuditLog.stop_trial(current_user.id, user.id)

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

    @action(
        "clear_delete_on",
        "Remove scheduled deletion of user",
        "This will remove the scheduled deletion for this users",
    )
    def clean_delete_on(self, ids):
        for user in User.filter(User.id.in_(ids)):
            user.delete_on = None

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
            emit_user_audit_log(
                user=user,
                action=UserAuditLogAction.Upgrade,
                message=f"Admin {current_user.email} extended manual subscription to user {user.email}",
            )
            EventDispatcher.send_event(
                user=user,
                content=EventContent(
                    user_plan_change=UserPlanChanged(
                        plan_end_time=manual_sub.end_at.timestamp
                    )
                ),
            )
            flash(f"Subscription extended to {manual_sub.end_at.humanize()}", "success")
        else:
            emit_user_audit_log(
                user=user,
                action=UserAuditLogAction.Upgrade,
                message=f"Admin {current_user.email} created manual subscription to user {user.email}",
            )
            manual_sub = ManualSubscription.create(
                user_id=user.id,
                end_at=arrow.now().shift(years=1, days=1),
                comment=way,
                is_giveaway=is_giveaway,
            )
            EventDispatcher.send_event(
                user=user,
                content=EventContent(
                    user_plan_change=UserPlanChanged(
                        plan_end_time=manual_sub.end_at.timestamp
                    )
                ),
            )

            flash(f"New {way} manual subscription for {user} is created", "success")
    Session.commit()


class EmailLogAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "mailbox.email", "contact.website_email"]

    can_edit = False
    can_create = False

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }


class AliasAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "email", "mailbox.email"]
    column_filters = ["id", "user.email", "email", "mailbox.email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

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
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "email"]
    column_filters = ["id", "user.email", "email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }


# class LifetimeCouponAdmin(SLModelView):
#     can_edit = True
#     can_create = True


class CouponAdmin(SLModelView):
    form_base_class = SecureForm
    can_edit = False
    can_create = True

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }


class ManualSubscriptionAdmin(SLModelView):
    form_base_class = SecureForm
    can_edit = True
    column_searchable_list = ["id", "user.email"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

    @action(
        "extend_1y",
        "Extend for 1 year",
        "Extend 1 year more?",
    )
    def extend_1y(self, ids):
        self.__extend_manual_subscription(ids, msg="1 year", years=1)

    @action(
        "extend_1m",
        "Extend for 1 month",
        "Extend 1 month more?",
    )
    def extend_1m(self, ids):
        self.__extend_manual_subscription(ids, msg="1 month", months=1)

    def __extend_manual_subscription(self, ids: List[int], msg: str, **kwargs):
        for ms in ManualSubscription.filter(ManualSubscription.id.in_(ids)):
            sub: ManualSubscription = ms
            sub.end_at = sub.end_at.shift(**kwargs)
            flash(f"Extend subscription for {msg} for {sub.user}", "success")
            emit_user_audit_log(
                user=sub.user,
                action=UserAuditLogAction.Upgrade,
                message=f"Admin {current_user.email} extended manual subscription for {msg} for {sub.user}",
            )
            AdminAuditLog.extend_subscription(
                current_user.id, sub.user.id, sub.end_at, msg
            )
            EventDispatcher.send_event(
                user=sub.user,
                content=EventContent(
                    user_plan_change=UserPlanChanged(plan_end_time=sub.end_at.timestamp)
                ),
            )

        Session.commit()


# class ClientAdmin(SLModelView):
#     column_searchable_list = ["name", "description", "user.email"]
#     column_exclude_list = ["oauth_client_secret", "home_url"]
#     can_edit = True


class CustomDomainAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["domain", "user.email", "user.id"]
    column_exclude_list = ["ownership_txt_token"]
    can_edit = False

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }


class ReferralAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.email", "code", "name"]
    column_filters = ["id", "user.email", "code", "name"]

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
    }

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


class AdminAuditLogAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["admin.id", "admin.email", "model_id", "created_at"]
    column_filters = ["admin.id", "admin.email", "model_id", "created_at"]
    column_exclude_list = ["id"]
    column_hide_backrefs = False
    can_edit = False
    can_create = False
    can_delete = False

    column_formatters = {
        "action": _admin_action_formatter,
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
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
    form_base_class = SecureForm
    column_searchable_list = ["id", "user.id", "created_at"]
    column_filters = ["user.id", "state"]
    column_hide_backrefs = False
    can_edit = False
    can_create = False
    can_delete = False

    column_formatters = {
        "created_at": _admin_date_formatter,
        "updated_at": _admin_date_formatter,
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
    form_base_class = SecureForm
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

    @action(
        "clone_newsletter",
        "Clone this newsletter",
    )
    def clone_newsletter(self, newsletter_ids):
        if len(newsletter_ids) != 1:
            flash("you can only select 1 newsletter", "error")
            return

        newsletter_id = newsletter_ids[0]
        newsletter: Newsletter = Newsletter.get(newsletter_id)
        new_newsletter = Newsletter.create(
            subject=newsletter.subject,
            html=newsletter.html,
            plain_text=newsletter.plain_text,
            commit=True,
        )

        flash(f"Newsletter {new_newsletter.subject} has been cloned", "success")


class NewsletterUserAdmin(SLModelView):
    form_base_class = SecureForm
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "newsletter.subject"]
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_edit = False
    can_create = False


class DailyMetricAdmin(SLModelView):
    form_base_class = SecureForm
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_export = True


class MetricAdmin(SLModelView):
    form_base_class = SecureForm
    column_exclude_list = ["created_at", "updated_at", "id"]

    can_export = True


class InvalidMailboxDomainAdmin(SLModelView):
    form_base_class = SecureForm
    can_create = True
    can_delete = True


class EmailSearchResult:
    def __init__(self):
        self.no_match: bool = True
        self.alias: Optional[Alias] = None
        self.alias_audit_log: Optional[List[AliasAuditLog]] = None
        self.mailbox: List[Mailbox] = []
        self.mailbox_count: int = 0
        self.deleted_alias: Optional[DeletedAlias] = None
        self.deleted_alias_audit_log: Optional[List[AliasAuditLog]] = None
        self.domain_deleted_alias: Optional[DomainDeletedAlias] = None
        self.domain_deleted_alias_audit_log: Optional[List[AliasAuditLog]] = None
        self.user: Optional[User] = None
        self.user_audit_log: Optional[List[UserAuditLog]] = None
        self.query: str

    @staticmethod
    def from_request_email(email: str) -> EmailSearchResult:
        output = EmailSearchResult()
        output.query = email
        alias = Alias.get_by(email=email)
        if alias:
            output.alias = alias
            output.alias_audit_log = (
                AliasAuditLog.filter_by(alias_id=alias.id)
                .order_by(AliasAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False
        try:
            user_id = int(email)
            user = User.get(user_id)
        except ValueError:
            user = User.get_by(email=email)
        if user:
            output.user = user
            output.user_audit_log = (
                UserAuditLog.filter_by(user_id=user.id)
                .order_by(UserAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False

        user_audit_log = (
            UserAuditLog.filter_by(user_email=email)
            .order_by(UserAuditLog.created_at.desc())
            .all()
        )
        if user_audit_log:
            output.user_audit_log = user_audit_log
            output.no_match = False
        mailboxes = (
            Mailbox.filter_by(email=email).order_by(Mailbox.id.desc()).limit(10).all()
        )
        if mailboxes:
            output.mailbox = mailboxes
            output.mailbox_count = Mailbox.filter_by(email=email).count()
            output.no_match = False
        deleted_alias = DeletedAlias.get_by(email=email)
        if deleted_alias:
            output.deleted_alias = deleted_alias
            output.deleted_alias_audit_log = (
                AliasAuditLog.filter_by(alias_email=deleted_alias.email)
                .order_by(AliasAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False
        domain_deleted_alias = DomainDeletedAlias.get_by(email=email)
        if domain_deleted_alias:
            output.domain_deleted_alias = domain_deleted_alias
            output.domain_deleted_alias_audit_log = (
                AliasAuditLog.filter_by(alias_email=domain_deleted_alias.email)
                .order_by(AliasAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False
        return output


class EmailSearchHelpers:
    @staticmethod
    def mailbox_list(user: User) -> list[Mailbox]:
        return (
            Mailbox.filter_by(user_id=user.id)
            .order_by(Mailbox.id.asc())
            .limit(10)
            .all()
        )

    @staticmethod
    def mailbox_count(user: User) -> int:
        return Mailbox.filter_by(user_id=user.id).order_by(Mailbox.id.desc()).count()

    @staticmethod
    def alias_mailboxes(alias: Alias) -> list[Mailbox]:
        return (
            Session.query(Mailbox)
            .filter(Mailbox.id == Alias.mailbox_id, Alias.id == alias.id)
            .union(
                Session.query(Mailbox)
                .join(AliasMailbox, Mailbox.id == AliasMailbox.mailbox_id)
                .filter(AliasMailbox.alias_id == alias.id)
            )
            .order_by(Mailbox.id)
            .limit(10)
            .all()
        )

    @staticmethod
    def alias_mailbox_count(alias: Alias) -> int:
        return len(alias.mailboxes)

    @staticmethod
    def alias_list(user: User) -> list[Alias]:
        return (
            Alias.filter_by(user_id=user.id).order_by(Alias.id.desc()).limit(10).all()
        )

    @staticmethod
    def alias_count(user: User) -> int:
        return Alias.filter_by(user_id=user.id).count()

    @staticmethod
    def partner_user(user: User) -> Optional[PartnerUser]:
        return PartnerUser.get_by(user_id=user.id)


class EmailSearchAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        search = EmailSearchResult()
        email = request.args.get("query")
        if email is not None and len(email) > 0:
            email = email.strip()
            search = EmailSearchResult.from_request_email(email)

        return self.render(
            "admin/email_search.html",
            email=email,
            data=search,
            helper=EmailSearchHelpers,
        )

    @expose("/partner_unlink", methods=["POST"])
    def delete_partner_link(self):
        user_id = request.form.get("user_id")
        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        try:
            user_id = int(user_id)
        except ValueError:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))
        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))
        external_user_id = perform_proton_account_unlink(user, skip_check=True)
        if not external_user_id:
            flash("User unlinked", "success")
            return redirect(url_for("admin.email_search.index", query=user_id))

        AdminAuditLog.create(
            admin_user_id=user.id,
            model=User.__class__.__name__,
            model_id=user.id,
            action=AuditLogActionEnum.unlink_user.value,
            data={"external_user_id": external_user_id},
        )
        Session.commit()

        return redirect(url_for("admin.email_search.index", query=user_id))


class CustomDomainWithValidationData:
    def __init__(self, domain: CustomDomain):
        self.domain: CustomDomain = domain
        self.ownership_expected: Optional[ExpectedValidationRecords] = None
        self.ownership_validation: Optional[DomainValidationResult] = None
        self.mx_expected: Optional[dict[int, ExpectedValidationRecords]] = None
        self.mx_validation: Optional[DomainValidationResult] = None
        self.spf_expected: Optional[ExpectedValidationRecords] = None
        self.spf_validation: Optional[DomainValidationResult] = None
        self.dkim_expected: {str: ExpectedValidationRecords} = {}
        self.dkim_validation: {str: str} = {}


class CustomDomainSearchResult:
    def __init__(self):
        self.no_match: bool = False
        self.user: Optional[User] = None
        self.domains: list[CustomDomainWithValidationData] = []

    @staticmethod
    def from_user(user: Optional[User]) -> CustomDomainSearchResult:
        out = CustomDomainSearchResult()
        if user is None:
            out.no_match = True
            return out
        out.user = user
        dns_client = get_network_dns_client()
        validator = CustomDomainValidation(
            dkim_domain=config.EMAIL_DOMAIN,
            partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
            partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
            dns_client=dns_client,
        )
        for custom_domain in user.custom_domains:
            validation_data = CustomDomainWithValidationData(custom_domain)
            if not custom_domain.ownership_verified:
                validation_data.ownership_expected = (
                    validator.get_ownership_verification_record(custom_domain)
                )
                validation_data.ownership_validation = (
                    validator.validate_domain_ownership(custom_domain)
                )
            if not custom_domain.verified:
                validation_data.mx_expected = validator.get_expected_mx_records(
                    custom_domain
                )
                validation_data.mx_validation = validator.validate_mx_records(
                    custom_domain
                )
            if not custom_domain.spf_verified:
                validation_data.spf_expected = validator.get_expected_spf_record(
                    custom_domain
                )
                validation_data.spf_validation = validator.validate_spf_records(
                    custom_domain
                )
            if not custom_domain.dkim_verified:
                validation_data.dkim_expected = validator.get_dkim_records(
                    custom_domain
                )
                validation_data.dkim_validation = validator.validate_dkim_records(
                    custom_domain
                )
            out.domains.append(validation_data)

        return out


class CustomDomainSearchAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        query = request.args.get("user")
        if query is None:
            search = CustomDomainSearchResult()
        else:
            try:
                user_id = int(query)
                user = User.get_by(id=user_id)
            except ValueError:
                user = User.get_by(email=query)
                if user is None:
                    cd = CustomDomain.get_by(domain=query)
                    if cd is not None:
                        user = cd.user
            search = CustomDomainSearchResult.from_user(user)

        return self.render(
            "admin/custom_domain_search.html",
            data=search,
            query=query,
        )

    @expose("/delete_domain", methods=["POST"])
    def delete_custom_domain(self):
        domain_id = request.form.get("domain_id")
        if not domain_id:
            flash("Missing domain_id", "error")
            return redirect(url_for("admin.custom_domain_search.index"))
        try:
            domain_id = int(domain_id)
        except ValueError:
            flash("Missing domain_id", "error")
            return redirect(url_for("admin.custom_domain_search.index"))
        domain: Optional[CustomDomain] = CustomDomain.get(domain_id)
        if domain is None:
            flash("Domain not found", "error")
            return redirect(url_for("admin.custom_domain_search.index"))

        domain_user_email = domain.user.email
        domain_domain = domain.domain
        from app.custom_domain_utils import delete_custom_domain

        delete_custom_domain(domain)

        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model=CustomDomain.__class__.__name__,
            model_id=domain_id,
            action=AuditLogActionEnum.delete_custom_domain.value,
            data={"domain": domain_domain},
        )
        Session.commit()

        flash("Scheduled deletion of custom domain", "success")
        return redirect(
            url_for("admin.custom_domain_search.index", user=domain_user_email)
        )


class AbuserLookupResult:
    def __init__(self):
        self.no_match: bool = False
        self.email: Optional[str] = None
        self.bundles: Optional[List[Dict]] = None

    @staticmethod
    def from_email(email: Optional[str]) -> AbuserLookupResult:
        out = AbuserLookupResult()

        if email is None or email == "":
            out.no_match = True

            return out

        out.email = email
        bundles = get_abuser_bundles_for_address(
            target_address=email,
            admin_id=current_user.id,
        )

        if not bundles:
            out.no_match = True

            return out

        for bundle in bundles:
            bundle_json = json.dumps(bundle)
            bundle["json"] = bundle_json

            user = User.get(int(bundle.get("account_id")))
            bundle["user"] = user

            AbuserLookupResult.convert_dt(bundle, "user_created_at")

            for mailbox_item in bundle.get("mailboxes", []):
                AbuserLookupResult.convert_dt(mailbox_item)

            for alias_item in bundle.get("aliases", []):
                AbuserLookupResult.convert_dt(alias_item)

        out.bundles = bundles

        return out

    @staticmethod
    def convert_dt(item: Dict, key: str = "created_at"):
        raw_date = item.get(key, "")

        if raw_date:
            item[key] = datetime.fromisoformat(raw_date)


class AbuserLookupAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        query = request.args.get("email")

        if query is None:
            result = AbuserLookupResult()
        else:
            email = sanitize_email(query)
            result = AbuserLookupResult.from_email(email)

        return self.render(
            "admin/abuser_lookup.html",
            data=result,
            query=query,
        )
