import arrow
from flask import redirect, url_for, request, flash
from flask_admin import expose, AdminIndexView
from flask_admin.actions import action
from flask_admin.contrib import sqla
from flask_login import current_user

from app.extensions import db
from app.models import User, ManualSubscription


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


class SLAdminIndexView(AdminIndexView):
    @expose("/")
    def index(self):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("auth.login", next=request.url))

        return redirect("/admin/user")


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
    can_edit = True

    def scaffold_list_columns(self):
        ret = super().scaffold_list_columns()
        ret.insert(0, "upgrade_channel")
        ret.insert(0, "premium_end")
        return ret

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
        "extend_trial_1w",
        "Extend trial for 1 week more",
        "Extend trial for 1 week more?",
    )
    def extend_trial_1w(self, ids):
        for user in User.query.filter(User.id.in_(ids)):
            if user.trial_end and user.trial_end > arrow.now():
                user.trial_end = user.trial_end.shift(weeks=1)
            else:
                user.trial_end = arrow.now().shift(weeks=1)

            flash(f"Extend trial for {user} to {user.trial_end}", "success")

        db.session.commit()


def manual_upgrade(way: str, ids: [int], is_giveaway: bool):
    query = User.query.filter(User.id.in_(ids))

    for user in query.all():
        manual_sub: ManualSubscription = ManualSubscription.get_by(user_id=user.id)
        if manual_sub:
            # renew existing subscription
            if manual_sub.end_at > arrow.now():
                manual_sub.end_at = manual_sub.end_at.shift(years=1)
            else:
                manual_sub.end_at = arrow.now().shift(years=1, days=1)
            db.session.commit()
            flash(f"Subscription extended to {manual_sub.end_at.humanize()}", "success")
            continue

        # user can have manual subscription applied if their current subscription is canceled
        if (
            user.is_premium()
            and not user.in_trial()
            and not user.subscription_cancelled
        ):
            flash(f"User {user} is already premium", "warning")
            continue

        ManualSubscription.create(
            user_id=user.id,
            end_at=arrow.now().shift(years=1, days=1),
            comment=way,
            is_giveaway=is_giveaway,
            commit=True,
        )

        flash(f"New {way} manual subscription for {user} is created", "success")


class EmailLogAdmin(SLModelView):
    column_searchable_list = ["id"]
    column_filters = ["id", "user.email", "mailbox.email", "contact.website_email"]

    can_edit = False
    can_create = False


class AliasAdmin(SLModelView):
    column_searchable_list = ["id", "user.email", "email", "mailbox.email"]
    column_filters = ["id", "user.email", "email", "mailbox.email"]


class MailboxAdmin(SLModelView):
    column_searchable_list = ["id", "user.email", "email"]
    column_filters = ["id", "user.email", "email"]


class LifetimeCouponAdmin(SLModelView):
    can_edit = True
    can_create = True


class CouponAdmin(SLModelView):
    can_edit = True
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
        for ms in ManualSubscription.query.filter(ManualSubscription.id.in_(ids)):
            ms.end_at = ms.end_at.shift(years=1)
            flash(f"Extend subscription for {ms.user}", "success")

        db.session.commit()


class ClientAdmin(SLModelView):
    column_searchable_list = ["name", "description", "user.email"]
    column_exclude_list = ["oauth_client_secret", "home_url"]
    can_edit = True


class ReferralAdmin(SLModelView):
    column_searchable_list = ["id", "user.email", "code", "name"]
    column_filters = ["id", "user.email", "code", "name"]

    def scaffold_list_columns(self):
        ret = super().scaffold_list_columns()
        ret.insert(0, "nb_user")
        ret.insert(0, "nb_paid_user")
        return ret


class PayoutAdmin(SLModelView):
    column_searchable_list = ["id", "user.email"]
    column_filters = ["id", "user.email"]
    can_edit = True
    can_create = True
    can_delete = True
