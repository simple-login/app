import arrow
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.config import PAGE_LIMIT
from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.models import GenEmail, EmailLog, Contact


class AliasLog:
    website_email: str
    website_from: str
    alias: str
    when: arrow.Arrow
    is_reply: bool
    blocked: bool
    bounced: bool
    mailbox: str

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


@dashboard_bp.route(
    "/alias_log/<int:alias_id>", methods=["GET"], defaults={"page_id": 0}
)
@dashboard_bp.route("/alias_log/<int:alias_id>/<int:page_id>")
@login_required
def alias_log(alias_id, page_id):
    gen_email = GenEmail.get(alias_id)

    # sanity check
    if not gen_email:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    if gen_email.user_id != current_user.id:
        flash("You do not have access to this page", "warning")
        return redirect(url_for("dashboard.index"))

    logs = get_alias_log(gen_email, page_id)
    base = (
        db.session.query(Contact, EmailLog)
        .filter(Contact.id == EmailLog.contact_id)
        .filter(Contact.gen_email_id == gen_email.id)
    )
    total = base.count()
    email_forwarded = (
        base.filter(EmailLog.is_reply == False)
        .filter(EmailLog.blocked == False)
        .count()
    )
    email_replied = base.filter(EmailLog.is_reply == True).count()
    email_blocked = base.filter(EmailLog.blocked == True).count()
    last_page = (
        len(logs) < PAGE_LIMIT
    )  # lightweight pagination without counting all objects

    return render_template("dashboard/alias_log.html", **locals())


def get_alias_log(gen_email: GenEmail, page_id=0):
    logs: [AliasLog] = []
    mailbox = gen_email.mailbox_email()

    q = (
        db.session.query(Contact, EmailLog)
        .filter(Contact.id == EmailLog.contact_id)
        .filter(Contact.gen_email_id == gen_email.id)
        .order_by(EmailLog.id.desc())
        .limit(PAGE_LIMIT)
        .offset(page_id * PAGE_LIMIT)
    )

    for fe, fel in q:
        al = AliasLog(
            website_email=fe.website_email,
            website_from=fe.website_from,
            alias=gen_email.email,
            when=fel.created_at,
            is_reply=fel.is_reply,
            blocked=fel.blocked,
            bounced=fel.bounced,
            mailbox=mailbox,
        )
        logs.append(al)
    logs = sorted(logs, key=lambda l: l.when, reverse=True)

    return logs
