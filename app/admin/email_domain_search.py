from __future__ import annotations

from typing import List

from flask import redirect, url_for, request, flash
from flask_admin import BaseView, expose
from flask_login import current_user
from sqlalchemy import or_

from app.abuser import mark_user_as_abuser
from app.models import User, Mailbox
from app.admin.email_search import EmailSearchHelpers


class EmailDomainSearchResult:
    def __init__(self):
        self.no_match: bool = False
        self.users: List[User] = []

    @staticmethod
    def from_mailboxes(users: List[User]) -> EmailDomainSearchResult:
        out = EmailDomainSearchResult()
        if not users:
            out.no_match = True
            return out
        out.users = users
        return out


class EmailDomainSearchAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/disable_user", methods=["POST"])
    def disable_user(self):
        query = request.form.get("query")
        user_id = request.form.get("user_id")
        if not user_id:
            return redirect(url_for("admin.email_domain_search.index", query=query))
        user = User.get(int(user_id))
        if not user:
            flash(
                f"Cannot find user with {user_id}",
                "warning",
            )
            return redirect(url_for("admin.email_domain_search.index", query=query))
        mark_user_as_abuser(
            user,
            f"Marked as abuser from the email domain search in the admin panel while searching for '{query}'",
        )
        flash(
            f"Marked user {user.email} ({user.id}) as abuser",
            "warning",
        )
        return redirect(url_for("admin.email_domain_search.index", query=query))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        query = request.args.get("query")
        if not query:
            search = EmailDomainSearchResult()
        else:
            users = (
                User.query()
                .join(Mailbox, User.id == Mailbox.user_id, isouter=True)
                .filter(
                    User.disabled.isnot(True),
                    or_(
                        User.email.like(f"%@{query}"), Mailbox.email.like(f"%@{query}")
                    ),
                )
                .order_by(User.id.asc())
                .limit(50)
                .all()
            )
            search = EmailDomainSearchResult.from_mailboxes(users)

        return self.render(
            "admin/mailbox_domain_search.html",
            data=search,
            query=query,
            helper=EmailSearchHelpers,
        )
