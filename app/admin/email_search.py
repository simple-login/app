from __future__ import annotations

from typing import Optional, List

from flask import redirect, url_for, request, flash
from flask_admin import BaseView, expose
from flask_login import current_user

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
        self.partner_users: List[PartnerUser] = []
        self.partner_users_found_by_regex: bool = False

    @staticmethod
    def search_aliases(query: str) -> EmailSearchResult:
        """Search for aliases by exact match or POSIX regex."""
        output = EmailSearchResult()
        output.query = query
        output.search_type = EmailSearchResult.SEARCH_TYPE_ALIAS

        # Try exact match first
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
        else:
            # Try regex search
            aliases = (
                Alias.filter(Alias.email.op("~")(query))
                .order_by(Alias.id.desc())
                .limit(10)
                .all()
            )
            if aliases:
                output.aliases = aliases
                output.aliases_found_by_regex = True
                output.no_match = False

        # Search deleted aliases
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
        else:
            # Try regex search for deleted aliases
            deleted_aliases = (
                DeletedAlias.filter(DeletedAlias.email.op("~")(query))
                .order_by(DeletedAlias.id.desc())
                .limit(10)
                .all()
            )
            if deleted_aliases:
                output.deleted_aliases = deleted_aliases
                output.deleted_aliases_found_by_regex = True
                output.no_match = False

        # Search domain deleted aliases
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
        else:
            # Try regex search for domain deleted aliases
            domain_deleted_aliases = (
                DomainDeletedAlias.filter(DomainDeletedAlias.email.op("~")(query))
                .order_by(DomainDeletedAlias.id.desc())
                .limit(10)
                .all()
            )
            if domain_deleted_aliases:
                output.domain_deleted_aliases = domain_deleted_aliases
                output.domain_deleted_aliases_found_by_regex = True
                output.no_match = False

        return output

    @staticmethod
    def search_emails(query: str) -> EmailSearchResult:
        """Search for mailboxes, users, and partner users by exact match or POSIX regex."""
        output = EmailSearchResult()
        output.query = query
        output.search_type = EmailSearchResult.SEARCH_TYPE_EMAIL

        # Search mailboxes
        mailbox = Mailbox.get_by(email=query)
        if mailbox:
            output.mailboxes = [mailbox]
            output.mailboxes_found_by_regex = False
            output.mailbox_count = 1
            output.no_match = False
        else:
            # Try regex search for mailboxes
            mailboxes = (
                Mailbox.filter(Mailbox.email.op("~")(query))
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
