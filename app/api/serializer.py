from dataclasses import dataclass
from typing import Optional

from arrow import Arrow
from sqlalchemy import or_, func, case, and_
from sqlalchemy.orm import joinedload

from app.config import PAGE_LIMIT
from app.db import Session
from app.models import (
    Alias,
    Contact,
    EmailLog,
    Mailbox,
    AliasMailbox,
    CustomDomain,
    User,
)


@dataclass
class AliasInfo:
    alias: Alias
    mailbox: Mailbox
    mailboxes: [Mailbox]

    nb_forward: int
    nb_blocked: int
    nb_reply: int

    latest_email_log: EmailLog = None
    latest_contact: Contact = None
    custom_domain: Optional[CustomDomain] = None

    def contain_mailbox(self, mailbox_id: int) -> bool:
        return mailbox_id in [m.id for m in self.mailboxes]


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
        "name": alias_info.alias.name,
        # activity
        "nb_forward": alias_info.nb_forward,
        "nb_block": alias_info.nb_blocked,
        "nb_reply": alias_info.nb_reply,
        # mailbox
        "mailbox": {"id": alias_info.mailbox.id, "email": alias_info.mailbox.email},
        "mailboxes": [
            {"id": mailbox.id, "email": mailbox.email}
            for mailbox in alias_info.mailboxes
        ],
        "support_pgp": alias_info.alias.mailbox_support_pgp(),
        "disable_pgp": alias_info.alias.disable_pgp,
        "latest_activity": None,
        "pinned": alias_info.alias.pinned,
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


def serialize_contact(contact: Contact, existed=False) -> dict:
    res = {
        "id": contact.id,
        "creation_date": contact.created_at.format(),
        "creation_timestamp": contact.created_at.timestamp,
        "last_email_sent_date": None,
        "last_email_sent_timestamp": None,
        "contact": contact.website_email,
        "reverse_alias": contact.website_send_to(),
        "reverse_alias_address": contact.reply_email,
        "existed": existed,
        "block_forward": contact.block_forward,
    }

    email_log: EmailLog = contact.last_reply()
    if email_log:
        res["last_email_sent_date"] = email_log.created_at.format()
        res["last_email_sent_timestamp"] = email_log.created_at.timestamp

    return res


def get_alias_infos_with_pagination(user, page_id=0, query=None) -> [AliasInfo]:
    ret = []
    q = (
        Session.query(Alias)
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


def get_alias_infos_with_pagination_v3(
    user,
    page_id=0,
    query=None,
    sort=None,
    alias_filter=None,
    mailbox_id=None,
    directory_id=None,
    page_limit=PAGE_LIMIT,
    page_size=PAGE_LIMIT,
) -> [AliasInfo]:
    q = construct_alias_query(user)

    if query:
        q = q.filter(
            or_(
                Alias.email.ilike(f"%{query}%"),
                Alias.note.ilike(f"%{query}%"),
                # can't use match() here as it uses to_tsquery that expected a tsquery input
                # Alias.ts_vector.match(query),
                Alias.ts_vector.op("@@")(func.plainto_tsquery("english", query)),
                Alias.name.ilike(f"%{query}%"),
            )
        )

    if mailbox_id:
        q = q.join(
            AliasMailbox, Alias.id == AliasMailbox.alias_id, isouter=True
        ).filter(
            or_(Alias.mailbox_id == mailbox_id, AliasMailbox.mailbox_id == mailbox_id)
        )

    if directory_id:
        q = q.filter(Alias.directory_id == directory_id)

    if alias_filter == "enabled":
        q = q.filter(Alias.enabled)
    elif alias_filter == "disabled":
        q = q.filter(Alias.enabled.is_(False))
    elif alias_filter == "pinned":
        q = q.filter(Alias.pinned)
    elif alias_filter == "hibp":
        q = q.filter(Alias.hibp_breaches.any())

    if sort == "old2new":
        q = q.order_by(Alias.created_at)
    elif sort == "new2old":
        q = q.order_by(Alias.created_at.desc())
    elif sort == "a2z":
        q = q.order_by(Alias.email)
    elif sort == "z2a":
        q = q.order_by(Alias.email.desc())
    else:
        # default sorting
        latest_activity = case(
            [
                (Alias.created_at > EmailLog.created_at, Alias.created_at),
                (Alias.created_at < EmailLog.created_at, EmailLog.created_at),
            ],
            else_=Alias.created_at,
        )
        q = q.order_by(Alias.pinned.desc())
        q = q.order_by(latest_activity.desc())

    q = list(q.limit(page_limit).offset(page_id * page_size))

    ret = []
    for alias, contact, email_log, nb_reply, nb_blocked, nb_forward in q:
        ret.append(
            AliasInfo(
                alias=alias,
                mailbox=alias.mailbox,
                mailboxes=alias.mailboxes,
                nb_forward=nb_forward,
                nb_blocked=nb_blocked,
                nb_reply=nb_reply,
                latest_email_log=email_log,
                latest_contact=contact,
                custom_domain=alias.custom_domain,
            )
        )

    return ret


def get_alias_info(alias: Alias) -> AliasInfo:
    q = (
        Session.query(Contact, EmailLog)
        .filter(Contact.alias_id == alias.id)
        .filter(EmailLog.contact_id == Contact.id)
    )

    alias_info = AliasInfo(
        alias=alias,
        nb_blocked=0,
        nb_forward=0,
        nb_reply=0,
        mailbox=alias.mailbox,
        mailboxes=[alias.mailbox],
    )

    for _, el in q:
        if el.is_reply:
            alias_info.nb_reply += 1
        elif el.blocked:
            alias_info.nb_blocked += 1
        else:
            alias_info.nb_forward += 1

    return alias_info


def get_alias_info_v2(alias: Alias, mailbox=None) -> AliasInfo:
    if not mailbox:
        mailbox = alias.mailbox

    q = (
        Session.query(Contact, EmailLog)
        .filter(Contact.alias_id == alias.id)
        .filter(EmailLog.contact_id == Contact.id)
    )

    latest_activity: Arrow = alias.created_at
    latest_email_log = None
    latest_contact = None

    alias_info = AliasInfo(
        alias=alias,
        nb_blocked=0,
        nb_forward=0,
        nb_reply=0,
        mailbox=mailbox,
        mailboxes=[mailbox],
    )

    for m in alias._mailboxes:
        alias_info.mailboxes.append(m)

    # remove duplicates
    # can happen that alias.mailbox_id also appears in AliasMailbox table
    alias_info.mailboxes = list(set(alias_info.mailboxes))

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
        Contact.filter_by(alias_id=alias.id)
        .order_by(Contact.id.desc())
        .limit(PAGE_LIMIT)
        .offset(page_id * PAGE_LIMIT)
    )

    res = []
    for fe in q.all():
        res.append(serialize_contact(fe))

    return res


def get_alias_info_v3(user: User, alias_id: int) -> AliasInfo:
    # use the same query construction in get_alias_infos_with_pagination_v3
    q = construct_alias_query(user)
    q = q.filter(Alias.id == alias_id)

    for alias, contact, email_log, nb_reply, nb_blocked, nb_forward in q:
        return AliasInfo(
            alias=alias,
            mailbox=alias.mailbox,
            mailboxes=alias.mailboxes,
            nb_forward=nb_forward,
            nb_blocked=nb_blocked,
            nb_reply=nb_reply,
            latest_email_log=email_log,
            latest_contact=contact,
            custom_domain=alias.custom_domain,
        )


def construct_alias_query(user: User):
    # subquery on alias annotated with nb_reply, nb_blocked, nb_forward, max_created_at, latest_email_log_created_at
    alias_activity_subquery = (
        Session.query(
            Alias.id,
            func.sum(case([(EmailLog.is_reply, 1)], else_=0)).label("nb_reply"),
            func.sum(
                case(
                    [(and_(EmailLog.is_reply.is_(False), EmailLog.blocked), 1)],
                    else_=0,
                )
            ).label("nb_blocked"),
            func.sum(
                case(
                    [
                        (
                            and_(
                                EmailLog.is_reply.is_(False),
                                EmailLog.blocked.is_(False),
                            ),
                            1,
                        )
                    ],
                    else_=0,
                )
            ).label("nb_forward"),
            func.max(EmailLog.created_at).label("latest_email_log_created_at"),
        )
        .join(EmailLog, Alias.id == EmailLog.alias_id, isouter=True)
        .filter(Alias.user_id == user.id)
        .group_by(Alias.id)
        .subquery()
    )

    alias_contact_subquery = (
        Session.query(Alias.id, func.max(Contact.id).label("max_contact_id"))
        .join(Contact, Alias.id == Contact.alias_id, isouter=True)
        .filter(Alias.user_id == user.id)
        .group_by(Alias.id)
        .subquery()
    )

    return (
        Session.query(
            Alias,
            Contact,
            EmailLog,
            alias_activity_subquery.c.nb_reply,
            alias_activity_subquery.c.nb_blocked,
            alias_activity_subquery.c.nb_forward,
        )
        .options(joinedload(Alias.hibp_breaches))
        .options(joinedload(Alias.custom_domain))
        .join(Contact, Alias.id == Contact.alias_id, isouter=True)
        .join(EmailLog, Contact.id == EmailLog.contact_id, isouter=True)
        .filter(Alias.id == alias_activity_subquery.c.id)
        .filter(Alias.id == alias_contact_subquery.c.id)
        .filter(
            or_(
                EmailLog.created_at
                == alias_activity_subquery.c.latest_email_log_created_at,
                and_(
                    # no email log yet for this alias
                    alias_activity_subquery.c.latest_email_log_created_at.is_(None),
                    # to make sure only 1 contact is returned in this case
                    or_(
                        Contact.id == alias_contact_subquery.c.max_contact_id,
                        alias_contact_subquery.c.max_contact_id.is_(None),
                    ),
                ),
            )
        )
    )
