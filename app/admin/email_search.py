from __future__ import annotations

from typing import Optional, List

import arrow
from flask import redirect, url_for, request, flash
from flask_admin import BaseView, expose
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.db import Session
from app.errors import ProtonPartnerNotSetUp
from app.models import (
    User,
    AdminAuditLog,
    Alias,
    Mailbox,
    DeletedAlias,
    DomainDeletedAlias,
    PartnerUser,
    AliasMailbox,
    AliasAuditLog,
    UserAuditLog,
    AuditLogActionEnum,
    AbuserAuditLog,
    CustomDomain,
)
from app.proton.proton_partner import get_proton_partner
from app.proton.proton_unlink import perform_proton_account_unlink


class EmailSearchResult:
    SEARCH_TYPE_ALIAS = "alias"
    SEARCH_TYPE_EMAIL = "email"

    def __init__(self):
        self.no_match: bool = True
        self.search_type: str = self.SEARCH_TYPE_EMAIL
        self.query: str = ""
        # Alias search results
        self.aliases: List[Alias] = []
        self.aliases_found_by_regex: bool = False
        self.alias_audit_log: Optional[List[AliasAuditLog]] = None
        self.deleted_aliases: List[DeletedAlias] = []
        self.deleted_aliases_found_by_regex: bool = False
        self.deleted_alias_audit_log: Optional[List[AliasAuditLog]] = None
        self.domain_deleted_aliases: List[DomainDeletedAlias] = []
        self.domain_deleted_aliases_found_by_regex: bool = False
        self.domain_deleted_alias_audit_log: Optional[List[AliasAuditLog]] = None
        # Email search results
        self.mailboxes: List[Mailbox] = []
        self.mailboxes_found_by_regex: bool = False
        self.mailbox_count: int = 0
        self.users: List[User] = []
        self.users_found_by_regex: bool = False
        self.user_audit_log: Optional[List[UserAuditLog]] = None
        self.abuser_audit_log: Optional[List[AbuserAuditLog]] = None
        self.admin_audit_log: Optional[List[AdminAuditLog]] = None
        self.partner_users: List[PartnerUser] = []
        self.partner_users_found_by_regex: bool = False

    @staticmethod
    def search_aliases(query: str) -> EmailSearchResult:
        """Search for aliases by exact match or POSIX regex."""
        output = EmailSearchResult()
        output.query = query
        output.search_type = EmailSearchResult.SEARCH_TYPE_ALIAS

        # Exact match only for alias search (no regex support)
        alias = Alias.get_by(email=query)
        if alias:
            output.aliases = [alias]
            output.aliases_found_by_regex = False
            output.alias_audit_log = (
                AliasAuditLog.filter_by(alias_id=alias.id)
                .order_by(AliasAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False

        # Search deleted aliases (exact match only)
        deleted_alias = DeletedAlias.get_by(email=query)
        if deleted_alias:
            output.deleted_aliases = [deleted_alias]
            output.deleted_aliases_found_by_regex = False
            output.deleted_alias_audit_log = (
                AliasAuditLog.filter_by(alias_email=deleted_alias.email)
                .order_by(AliasAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False

        # Search domain deleted aliases (exact match only)
        domain_deleted_alias = DomainDeletedAlias.get_by(email=query)
        if domain_deleted_alias:
            output.domain_deleted_aliases = [domain_deleted_alias]
            output.domain_deleted_aliases_found_by_regex = False
            output.domain_deleted_alias_audit_log = (
                AliasAuditLog.filter_by(alias_email=domain_deleted_alias.email)
                .order_by(AliasAuditLog.created_at.desc())
                .all()
            )
            output.no_match = False

        return output

    @staticmethod
    def search_emails(query: str) -> EmailSearchResult:
        """Search for mailboxes, users, and partner users by exact match or POSIX regex."""
        output = EmailSearchResult()
        output.query = query
        output.search_type = EmailSearchResult.SEARCH_TYPE_EMAIL

        # Search mailboxes (eager load user relationship for template display)
        mailbox = (
            Mailbox.filter_by(email=query).options(joinedload(Mailbox.user)).first()
        )
        if mailbox:
            output.mailboxes = [mailbox]
            output.mailboxes_found_by_regex = False
            output.mailbox_count = 1
            output.no_match = False
        else:
            # Try regex search for mailboxes
            mailboxes = (
                Mailbox.filter(Mailbox.email.op("~")(query))
                .options(joinedload(Mailbox.user))
                .order_by(Mailbox.id.desc())
                .limit(10)
                .all()
            )
            if mailboxes:
                output.mailboxes = mailboxes
                output.mailboxes_found_by_regex = True
                output.mailbox_count = len(mailboxes)
                output.no_match = False

        # Search users
        user = None
        try:
            user_id = int(query)
            user = User.get(user_id)
        except ValueError:
            user = User.get_by(email=query)

        if user:
            output.users = [user]
            output.users_found_by_regex = False
            output.user_audit_log = (
                UserAuditLog.filter_by(user_id=user.id)
                .order_by(UserAuditLog.created_at.desc())
                .limit(20)
                .all()
            )
            output.abuser_audit_log = (
                AbuserAuditLog.filter_by(user_id=user.id)
                .order_by(AbuserAuditLog.created_at.desc())
                .limit(20)
                .all()
            )
            output.admin_audit_log = (
                Session.query(AdminAuditLog)
                .filter(
                    AdminAuditLog.model == "User",
                    AdminAuditLog.model_id == user.id,
                )
                .order_by(AdminAuditLog.created_at.desc())
                .limit(20)
                .all()
            )
            output.no_match = False
        else:
            # Try regex search for users
            users = (
                User.filter(User.email.op("~")(query))
                .order_by(User.id.desc())
                .limit(10)
                .all()
            )
            if users:
                output.users = users
                output.users_found_by_regex = True
                output.no_match = False

        # Also check user audit log by user_email
        if not output.users:
            user_audit_log = (
                UserAuditLog.filter_by(user_email=query)
                .order_by(UserAuditLog.created_at.desc())
                .all()
            )
            if user_audit_log:
                output.user_audit_log = user_audit_log
                output.no_match = False

        # Search partner users
        try:
            proton_partner = get_proton_partner()
            partner_user = PartnerUser.filter_by(
                partner_id=proton_partner.id, partner_email=query
            ).first()
            if partner_user:
                output.partner_users = [partner_user]
                output.partner_users_found_by_regex = False
                output.no_match = False
            else:
                # Try regex search for partner users
                partner_users = (
                    PartnerUser.filter(
                        PartnerUser.partner_id == proton_partner.id,
                        PartnerUser.partner_email.op("~")(query),
                    )
                    .order_by(PartnerUser.id.desc())
                    .limit(10)
                    .all()
                )
                if partner_users:
                    output.partner_users = partner_users
                    output.partner_users_found_by_regex = True
                    output.no_match = False
        except ProtonPartnerNotSetUp:
            # Proton partner not configured, skip this search
            pass

        return output

    @staticmethod
    def from_request(query: str, search_type: str) -> EmailSearchResult:
        """Main entry point for searching based on search type."""
        if search_type == EmailSearchResult.SEARCH_TYPE_ALIAS:
            return EmailSearchResult.search_aliases(query)
        else:
            return EmailSearchResult.search_emails(query)


class EmailSearchHelpers:
    @staticmethod
    def mailbox_list(user: User, ensure_mailbox_id: int | None = None) -> list[Mailbox]:
        """Get first 10 mailboxes for user, ensuring a specific mailbox is included if provided."""
        mailboxes = (
            Mailbox.filter_by(user_id=user.id)
            .order_by(Mailbox.id.asc())
            .limit(10)
            .all()
        )
        # If a specific mailbox should be included and it's not in the list, add it
        if ensure_mailbox_id:
            mailbox_ids = {m.id for m in mailboxes}
            if ensure_mailbox_id not in mailbox_ids:
                ensure_mailbox = Mailbox.get(ensure_mailbox_id)
                if ensure_mailbox and ensure_mailbox.user_id == user.id:
                    mailboxes.insert(0, ensure_mailbox)
        return mailboxes

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

    @staticmethod
    def user_audit_log(user: User) -> list[UserAuditLog]:
        return (
            UserAuditLog.filter_by(user_id=user.id)
            .order_by(UserAuditLog.created_at.desc())
            .limit(20)
            .all()
        )

    @staticmethod
    def abuser_audit_log(user: User) -> list[AbuserAuditLog]:
        return (
            AbuserAuditLog.filter_by(user_id=user.id)
            .order_by(AbuserAuditLog.created_at.desc())
            .limit(20)
            .all()
        )

    @staticmethod
    def admin_audit_log(user: User) -> list[AdminAuditLog]:
        return (
            Session.query(AdminAuditLog)
            .filter(
                AdminAuditLog.model == "User",
                AdminAuditLog.model_id == user.id,
            )
            .order_by(AdminAuditLog.created_at.desc())
            .limit(20)
            .all()
        )

    @staticmethod
    def action_name(action_id: int) -> str:
        """Convert audit log action ID to human-readable name."""
        action_names = {
            0: "create_object",
            1: "update_object",
            2: "delete_object",
            3: "manual_upgrade",
            4: "extend_trial",
            5: "disable_2fa",
            6: "logged_as_user",
            7: "extend_subscription",
            8: "download_provider_complaint",
            9: "disable_user",
            10: "enable_user",
            11: "stop_trial",
            12: "unlink_user",
            13: "delete_custom_domain",
            14: "clear_delete_on",
            15: "update_subdomain_quota",
            16: "update_directory_quota",
        }
        return action_names.get(action_id, f"unknown_{action_id}")

    @staticmethod
    def get_admin_email(admin_id: int | None) -> str | None:
        """Get admin email by ID."""
        if not admin_id:
            return None
        admin = User.get(admin_id)
        return admin.email if admin else None

    @staticmethod
    def user_flags(user: User) -> list[str]:
        """Decode user flags into human-readable list."""
        flags = user.flags or 0
        result = []
        if flags & User.FLAG_FREE_DISABLE_CREATE_CONTACTS:
            result.append("FREE_DISABLE_CREATE_CONTACTS")
        if flags & User.FLAG_CREATED_FROM_PARTNER:
            result.append("CREATED_FROM_PARTNER")
        if flags & User.FLAG_FREE_OLD_ALIAS_LIMIT:
            result.append("FREE_OLD_ALIAS_LIMIT")
        if flags & User.FLAG_CREATED_ALIAS_FROM_PARTNER:
            result.append("CREATED_ALIAS_FROM_PARTNER")
        return result

    @staticmethod
    def alias_flags(alias: Alias) -> list[str]:
        """Decode alias flags into human-readable list."""
        flags = alias.flags or 0
        result = []
        if flags & Alias.FLAG_PARTNER_CREATED:
            result.append("PARTNER_CREATED")
        return result

    @staticmethod
    def custom_domain_list(user: User) -> list[CustomDomain]:
        """Get list of custom domains for a user."""
        # user.custom_domains is a backref relationship (InstrumentedList)
        return list(user.custom_domains)  # type: ignore[arg-type]

    @staticmethod
    def custom_domain_count(user: User) -> int:
        """Get count of custom domains for a user."""
        return len(user.custom_domains)  # type: ignore[arg-type]

    @staticmethod
    def domain_alias_count(domain: CustomDomain) -> int:
        """Get count of aliases for a custom domain."""
        return Alias.filter(Alias.custom_domain_id == domain.id).count()

    @staticmethod
    def domain_deleted_alias_count(domain: CustomDomain) -> int:
        """Get count of deleted aliases for a custom domain."""
        # DomainDeletedAlias stores deleted aliases for custom domains
        return DomainDeletedAlias.filter(
            DomainDeletedAlias.domain_id == domain.id
        ).count()

    @staticmethod
    def subscription_end_date(subscription):
        """Get the end date for any subscription type."""
        if subscription is None:
            return None

        sub_class = subscription.__class__.__name__

        if sub_class == "Subscription":
            # Paddle subscription uses next_bill_date (Date type)
            if subscription.next_bill_date:
                return arrow.get(subscription.next_bill_date)
        elif sub_class == "ManualSubscription":
            return subscription.end_at
        elif sub_class == "CoinbaseSubscription":
            return subscription.end_at
        elif sub_class == "AppleSubscription":
            return subscription.expires_date
        elif sub_class == "PartnerSubscription":
            return subscription.end_at

        return None


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
        query = request.args.get("query")
        search_type = request.args.get(
            "search_type", EmailSearchResult.SEARCH_TYPE_EMAIL
        )
        if query is not None and len(query) > 0:
            query = query.strip()
            search = EmailSearchResult.from_request(query, search_type)

        return self.render(
            "admin/email_search.html",
            query=query,
            search_type=search_type,
            data=search,
            helper=EmailSearchHelpers,
            now=arrow.now(),
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

        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model="User",
            model_id=user.id,
            action=AuditLogActionEnum.unlink_user.value,
            data={"external_user_id": external_user_id or "unknown"},
        )
        Session.commit()

        flash("User unlinked from Proton account", "success")
        return redirect(url_for("admin.email_search.index", query=user.email))

    @expose("/stop_user_deletion", methods=["POST"])
    def stop_user_deletion(self):
        user_id = request.form.get("user_id")
        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        try:
            user_id = int(user_id)
        except ValueError:
            flash("Invalid user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        if user.delete_on is None:
            flash("User is not scheduled for deletion", "warning")
            return redirect(url_for("admin.email_search.index", query=user.email))

        user.delete_on = None
        AdminAuditLog.clear_delete_on(current_user.id, user.id)
        Session.commit()

        flash(f"Cancelled scheduled deletion for user {user.email}", "success")
        return redirect(url_for("admin.email_search.index", query=user.email))

    @expose("/update_subdomain_quota", methods=["POST"])
    def update_subdomain_quota(self):
        user_id = request.form.get("user_id")
        new_quota = request.form.get("subdomain_quota")

        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        if not new_quota:
            flash("Missing subdomain quota value", "error")
            return redirect(url_for("admin.email_search.index"))

        try:
            user_id = int(user_id)
            new_quota = int(new_quota)
        except ValueError:
            flash("Invalid user_id or quota value", "error")
            return redirect(url_for("admin.email_search.index"))

        if new_quota < 0:
            flash("Subdomain quota cannot be negative", "error")
            return redirect(url_for("admin.email_search.index"))

        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        old_quota = user._subdomain_quota
        user._subdomain_quota = new_quota
        AdminAuditLog.update_subdomain_quota(
            current_user.id, user.id, old_quota, new_quota
        )
        Session.commit()

        flash(
            f"Updated subdomain quota for user {user.email} from {old_quota} to {new_quota}",
            "success",
        )
        return redirect(url_for("admin.email_search.index", query=user.email))

    @expose("/update_directory_quota", methods=["POST"])
    def update_directory_quota(self):
        user_id = request.form.get("user_id")
        new_quota = request.form.get("directory_quota")

        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        if not new_quota:
            flash("Missing directory quota value", "error")
            return redirect(url_for("admin.email_search.index"))

        try:
            user_id = int(user_id)
            new_quota = int(new_quota)
        except ValueError:
            flash("Invalid user_id or quota value", "error")
            return redirect(url_for("admin.email_search.index"))

        if new_quota < 0:
            flash("Directory quota cannot be negative", "error")
            return redirect(url_for("admin.email_search.index"))

        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        old_quota = user._directory_quota
        user._directory_quota = new_quota
        AdminAuditLog.update_directory_quota(
            current_user.id, user.id, old_quota, new_quota
        )
        Session.commit()

        flash(
            f"Updated directory quota for user {user.email} from {old_quota} to {new_quota}",
            "success",
        )
        return redirect(url_for("admin.email_search.index", query=user.email))

    @expose("/mark_abuser", methods=["POST"])
    def mark_abuser(self):
        from app.abuser import mark_user_as_abuser

        user_id = request.form.get("user_id")
        note = request.form.get("note", "").strip()

        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        if not note:
            flash("Note is required when marking a user as abuser", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        try:
            user_id = int(user_id)
        except ValueError:
            flash("Invalid user_id", "error")
            return redirect(url_for("admin.email_search.index"))

        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        if user.disabled:
            flash(f"User {user.email} is already disabled/marked as abuser", "warning")
            return redirect(url_for("admin.email_search.index", query=user.email))

        mark_user_as_abuser(user, note, admin_id=current_user.id)

        flash(f"Marked user {user.email} as abuser", "success")
        return redirect(url_for("admin.email_search.index", query=user.email))

    @expose("/unmark_abuser", methods=["POST"])
    def unmark_abuser(self):
        from app.abuser import unmark_as_abusive_user

        user_id = request.form.get("user_id")
        note = request.form.get("note", "").strip()

        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))
        if not note:
            flash("Note is required when unmarking a user as abuser", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        try:
            user_id = int(user_id)
        except ValueError:
            flash("Invalid user_id", "error")
            return redirect(url_for("admin.email_search.index"))

        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        if not user.disabled:
            flash(f"User {user.email} is not disabled/marked as abuser", "warning")
            return redirect(url_for("admin.email_search.index", query=user.email))

        unmark_as_abusive_user(user.id, note, admin_id=current_user.id)

        flash(f"Unmarked user {user.email} as abuser", "success")
        return redirect(url_for("admin.email_search.index", query=user.email))

    @expose("/disable_2fa", methods=["POST"])
    def disable_2fa(self):
        user_id = request.form.get("user_id")

        if not user_id:
            flash("Missing user_id", "error")
            return redirect(url_for("admin.email_search.index"))

        try:
            user_id = int(user_id)
        except ValueError:
            flash("Invalid user_id", "error")
            return redirect(url_for("admin.email_search.index"))

        user = User.get(user_id)
        if user is None:
            flash("User not found", "error")
            return redirect(url_for("admin.email_search.index", query=user_id))

        had_totp = user.enable_otp
        had_fido = bool(user.fido_uuid)

        if not had_totp and not had_fido:
            flash(f"User {user.email} does not have 2FA enabled", "warning")
            return redirect(url_for("admin.email_search.index", query=user.email))

        # Disable TOTP
        if had_totp:
            user.enable_otp = False
            user.otp_secret = None

        # Disable FIDO/WebAuthn
        if had_fido:
            user.fido_uuid = None

        # Log the action
        disabled_methods = []
        if had_totp:
            disabled_methods.append("TOTP")
        if had_fido:
            disabled_methods.append("FIDO")

        AdminAuditLog.create(
            admin_user_id=current_user.id,
            model="User",
            model_id=user.id,
            action=AuditLogActionEnum.disable_2fa.value,
            data={"disabled_methods": disabled_methods},
        )
        Session.commit()

        flash(
            f"Disabled 2FA ({', '.join(disabled_methods)}) for user {user.email}",
            "success",
        )
        return redirect(url_for("admin.email_search.index", query=user.email))
