import arrow
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.config import PAGE_LIMIT
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.models import Alias, EmailLog, Contact


class AliasLog:
    website_email: str
    reverse_alias: str
    alias: str
    when: arrow.Arrow
    is_reply: bool
    blocked: bool
    bounced: bool
    email_log: EmailLog
    contact: Contact

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@dashboard_bp.route(
    "/alias_log/<int:alias_id>", methods=["GET"], defaults={"page_id": 0}
)
@dashboard_bp.route("/alias_log/<int:alias_id>/<int:page_id>")
@login_required
def alias_log(alias_id, page_id):
    alias = Alias.get(alias_id)

    # sanity check
    if not alias:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    if alias.user_id != current_user.id:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    logs = get_alias_log(alias, page_id)
    base = (
        Session.query(Contact, EmailLog)
        .filter(Contact.id == EmailLog.contact_id)
        .filter(Contact.alias_id == alias.id)
    )
    total = base.count()
    email_forwarded = (
        base.filter(EmailLog.is_reply.is_(False))
        .filter(EmailLog.blocked.is_(False))
        .count()
    )
    email_replied = base.filter(EmailLog.is_reply.is_(True)).count()
    email_blocked = base.filter(EmailLog.blocked.is_(True)).count()
    last_page = (
        len(logs) < PAGE_LIMIT
    )  # lightweight pagination without counting all objects

    return render_template("dashboard/alias_log.html", **locals())


def get_alias_log(alias: Alias, page_id=0) -> [AliasLog]:
    logs: [AliasLog] = []

    q = (
        Session.query(Contact, EmailLog)
        .filter(Contact.id == EmailLog.contact_id)
        .filter(Contact.alias_id == alias.id)
        .order_by(EmailLog.id.desc())
        .limit(PAGE_LIMIT)
        .offset(page_id * PAGE_LIMIT)
    )

    for contact, email_log in q:
        al = AliasLog(
            website_email=contact.website_email,
            reverse_alias=contact.website_send_to(),
            alias=alias.email,
            when=email_log.created_at,
            is_reply=email_log.is_reply,
            blocked=email_log.blocked,
            bounced=email_log.bounced,
            email_log=email_log,
            contact=contact,
        )
        logs.append(al)
    logs = sorted(logs, key=lambda l: l.when, reverse=True)

    return logs
