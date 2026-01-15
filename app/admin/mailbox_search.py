from __future__ import annotations

from typing import Optional, List

from flask import redirect, url_for, request, flash
from flask_admin import BaseView, expose
from flask_login import current_user
from sqlalchemy import or_, and_

from app.db import Session
from app.models import Alias, Mailbox, AliasMailbox
from app.admin.email_search import EmailSearchHelpers


class MailboxSearchResult:
    def __init__(self):
        self.no_match: bool = False
        self.mailbox: Optional[Mailbox] = None
        self.aliases: List[Alias] = []

    @staticmethod
    def from_mailbox(mbox: Optional[Mailbox]) -> MailboxSearchResult:
        out = MailboxSearchResult()
        if mbox is None:
            out.no_match = True
            return out
        out.mailbox = mbox
        out.aliases = mbox.aliases[:10]
        out.aliases = (
            Session.query(Alias)
            .join(
                AliasMailbox,
                and_(
                    AliasMailbox.alias_id == Alias.id,
                    AliasMailbox.mailbox_id == mbox.id,
                ),
                isouter=True,
            )
            .filter(
                or_(Alias.mailbox_id == mbox.id, AliasMailbox.mailbox_id == mbox.id)
            )
            .order_by(Alias.id)
            .limit(10)
            .all()
        )

        return out


class MailboxSearchAdmin(BaseView):
    def is_accessible(self):
        return current_user.is_authenticated and current_user.is_admin

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        flash("You don't have access to the admin page", "error")
        return redirect(url_for("dashboard.index", next=request.url))

    @expose("/", methods=["GET", "POST"])
    def index(self):
        query = request.args.get("query")
        if query is None:
            search = MailboxSearchResult()
        else:
            try:
                mailbox_id = int(query)
                mailbox = Mailbox.get_by(id=mailbox_id)
            except ValueError:
                mailbox = Mailbox.get_by(email=query)
            search = MailboxSearchResult.from_mailbox(mailbox)

        return self.render(
            "admin/mailbox_search.html",
            data=search,
            query=query,
            helper=EmailSearchHelpers,
        )
