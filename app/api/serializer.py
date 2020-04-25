from dataclasses import dataclass

from arrow import Arrow
from sqlalchemy import or_, func, case
from sqlalchemy.orm import joinedload

from app.config import PAGE_LIMIT
from app.extensions import db
from app.models import Alias, Contact, EmailLog, Mailbox


@dataclass
class AliasInfo:
    alias: Alias
    mailbox: Mailbox

    nb_forward: int
    nb_blocked: int
    nb_reply: int

    latest_email_log: EmailLog = None
    latest_contact: Contact = None


def serialize_alias_info(alias_info: AliasInfo) -> dict:
    return {
        # Alias field
        "id": alias_info.alias.id,
        "email": alias_info.alias.email,
        "creation_date": alias_info.alias.created_at.format(),
        "creation_timestamp": alias_info.alias.created_at.timestamp,
        "enabled": alias_info.alias.enabled,
        "note": alias_info.alias.note,
        # activity
        "nb_forward": alias_info.nb_forward,
        "nb_block": alias_info.nb_blocked,
        "nb_reply": alias_info.nb_reply,
    }


def serialize_alias_info_v2(alias_info: AliasInfo) -> dict:
    res = {
        # Alias field
        "id": alias_info.alias.id,
        "email": alias_info.alias.email,
        "creation_date": alias_info.alias.created_at.format(),
        "creation_timestamp": alias_info.alias.created_at.timestamp,
        "enabled": alias_info.alias.enabled,
        "note": alias_info.alias.note,
        # activity
        "nb_forward": alias_info.nb_forward,
        "nb_block": alias_info.nb_blocked,
        "nb_reply": alias_info.nb_reply,
        # mailbox
        "mailbox": {
            "id": alias_info.mailbox.id,
            "email": alias_info.mailbox.email
        }
    }
    if alias_info.latest_email_log:
        email_log = alias_info.latest_email_log
        contact = alias_info.latest_contact
        # latest activity
        res["latest_activity"] = {
            "timestamp": email_log.created_at.timestamp,
            "action": email_log.get_action(),
            "contact": {
                "email": contact.website_email,
                "name": contact.name,
                "reverse_alias": contact.website_send_to(),
            },
        }
    return res


def serialize_contact(contact: Contact) -> dict:
    res = {
        "id": contact.id,
        "creation_date": contact.created_at.format(),
        "creation_timestamp": contact.created_at.timestamp,
        "last_email_sent_date": None,
        "last_email_sent_timestamp": None,
        "contact": contact.website_email,
        "reverse_alias": contact.website_send_to(),
    }

    email_log: EmailLog = contact.last_reply()
    if email_log:
        res["last_email_sent_date"] = email_log.created_at.format()
        res["last_email_sent_timestamp"] = email_log.created_at.timestamp

    return res


def get_alias_infos_with_pagination(user, page_id=0, query=None) -> [AliasInfo]:
    ret = []
    q = (
        db.session.query(Alias)
        .options(joinedload(Alias.mailbox))
        .filter(Alias.user_id == user.id)
        .order_by(Alias.created_at.desc())
    )

    if query:
        q = q.filter(
            or_(Alias.email.ilike(f"%{query}%"), Alias.note.ilike(f"%{query}%"))
        )

    q = q.limit(PAGE_LIMIT).offset(page_id * PAGE_LIMIT)

    for alias in q:
        ret.append(get_alias_info(alias))

    return ret


def get_alias_infos_with_pagination_v2(
    user, page_id=0, query=None, sort=None
) -> [AliasInfo]:
    ret = []
    latest_activity = func.max(
        case(
            [
                (Alias.created_at > EmailLog.created_at, Alias.created_at),
                (Alias.created_at < EmailLog.created_at, EmailLog.created_at),
            ],
            else_=Alias.created_at,
        )
    ).label("latest")

    q = (
        db.session.query(Alias, Mailbox, latest_activity)
        .join(Contact, Alias.id == Contact.alias_id, isouter=True)
        .join(EmailLog, Contact.id == EmailLog.contact_id, isouter=True)
        .filter(Alias.user_id == user.id)
        .filter(Alias.mailbox_id == Mailbox.id)
    )

    if query:
        q = q.filter(
            or_(Alias.email.ilike(f"%{query}%"), Alias.note.ilike(f"%{query}%"))
        )

    if sort == "old2new":
        q = q.order_by(Alias.created_at)
    else:
        # default sorting
        q = q.order_by(latest_activity.desc())

    q = q.group_by(Alias.id, Mailbox.id)

    q = q.limit(PAGE_LIMIT).offset(page_id * PAGE_LIMIT)

    for alias, mailbox, latest_activity in q:
        ret.append(get_alias_info_v2(alias, mailbox))

    return ret


def get_alias_info(alias: Alias) -> AliasInfo:
    q = (
        db.session.query(Contact, EmailLog)
        .filter(Contact.alias_id == alias.id)
        .filter(EmailLog.contact_id == Contact.id)
    )

    alias_info = AliasInfo(
        alias=alias, nb_blocked=0, nb_forward=0, nb_reply=0, mailbox=alias.mailbox
    )

    for _, el in q:
        if el.is_reply:
            alias_info.nb_reply += 1
        elif el.blocked:
            alias_info.nb_blocked += 1
        else:
            alias_info.nb_forward += 1

    return alias_info


def get_alias_info_v2(alias: Alias, mailbox) -> AliasInfo:
    q = (
        db.session.query(Contact, EmailLog)
        .filter(Contact.alias_id == alias.id)
        .filter(EmailLog.contact_id == Contact.id)
    )

    latest_activity: Arrow = alias.created_at
    latest_email_log = None
    latest_contact = None

    alias_info = AliasInfo(
        alias=alias, nb_blocked=0, nb_forward=0, nb_reply=0, mailbox=mailbox
    )

    for contact, email_log in q:
        if email_log.is_reply:
            alias_info.nb_reply += 1
        elif email_log.blocked:
            alias_info.nb_blocked += 1
        else:
            alias_info.nb_forward += 1

        if email_log.created_at > latest_activity:
            latest_activity = email_log.created_at
            latest_email_log = email_log
            latest_contact = contact

    alias_info.latest_contact = latest_contact
    alias_info.latest_email_log = latest_email_log

    return alias_info


def get_alias_contacts(alias, page_id: int) -> [dict]:
    q = (
        Contact.query.filter_by(alias_id=alias.id)
        .order_by(Contact.id.desc())
        .limit(PAGE_LIMIT)
        .offset(page_id * PAGE_LIMIT)
    )

    res = []
    for fe in q.all():
        res.append(serialize_contact(fe))

    return res
