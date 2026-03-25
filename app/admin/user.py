from __future__ import annotations

import arrow
from flask import flash
from flask_admin.actions import action
from flask_admin.form import SecureForm
from flask_login import current_user

from app.abuser import mark_user_as_abuser, unmark_as_abusive_user
from app.admin.base import (
    SLModelView,
    _admin_date_formatter,
    _user_upgrade_channel_formatter,
)
from app.db import Session
from app.events.event_dispatcher import EventDispatcher
from app.events.generated.event_pb2 import EventContent, UserPlanChanged
from app.models import (
    User,
    ManualSubscription,
    Fido,
    Subscription,
    AppleSubscription,
    AdminAuditLog,
    PADDLE_SUBSCRIPTION_GRACE_DAYS,
)
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


def manual_upgrade(way: str, ids: list[int], is_giveaway: bool):
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
