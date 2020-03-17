from email.utils import parseaddr

from flask import g
from flask import jsonify
from flask import request
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.config import EMAIL_DOMAIN
from app.config import PAGE_LIMIT
from app.dashboard.views.alias_log import get_alias_log
from app.dashboard.views.index import get_alias_info, AliasInfo
from app.extensions import db
from app.log import LOG
from app.models import ForwardEmailLog
from app.models import GenEmail, Contact
from app.utils import random_string


@api_bp.route("/aliases")
@cross_origin()
@verify_api_key
def get_aliases():
    """
    Get aliases
    Input:
        page_id: in query
    Output:
        - aliases: list of alias:
            - id
            - email
            - creation_date
            - creation_timestamp
            - nb_forward
            - nb_block
            - nb_reply
            - note

    """
    user = g.user
    try:
        page_id = int(request.args.get("page_id"))
    except (ValueError, TypeError):
        return jsonify(error="page_id must be provided in request query"), 400

    aliases: [AliasInfo] = get_alias_info(user, page_id=page_id)

    return (
        jsonify(
            aliases=[
                {
                    "id": alias.id,
                    "email": alias.gen_email.email,
                    "creation_date": alias.gen_email.created_at.format(),
                    "creation_timestamp": alias.gen_email.created_at.timestamp,
                    "nb_forward": alias.nb_forward,
                    "nb_block": alias.nb_blocked,
                    "nb_reply": alias.nb_reply,
                    "enabled": alias.gen_email.enabled,
                    "note": alias.note,
                }
                for alias in aliases
            ]
        ),
        200,
    )


@api_bp.route("/aliases/<int:alias_id>", methods=["DELETE"])
@cross_origin()
@verify_api_key
def delete_alias(alias_id):
    """
    Delete alias
    Input:
        alias_id: in url
    Output:
        200 if deleted successfully

    """
    user = g.user
    gen_email = GenEmail.get(alias_id)

    if gen_email.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    GenEmail.delete(alias_id)
    db.session.commit()

    return jsonify(deleted=True), 200


@api_bp.route("/aliases/<int:alias_id>/toggle", methods=["POST"])
@cross_origin()
@verify_api_key
def toggle_alias(alias_id):
    """
    Enable/disable alias
    Input:
        alias_id: in url
    Output:
        200 along with new status:
        - enabled


    """
    user = g.user
    gen_email: GenEmail = GenEmail.get(alias_id)

    if gen_email.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    gen_email.enabled = not gen_email.enabled
    db.session.commit()

    return jsonify(enabled=gen_email.enabled), 200


@api_bp.route("/aliases/<int:alias_id>/activities")
@cross_origin()
@verify_api_key
def get_alias_activities(alias_id):
    """
    Get aliases
    Input:
        page_id: in query
    Output:
        - activities: list of activity:
            - from
            - to
            - timestamp
            - action: forward|reply|block

    """
    user = g.user
    try:
        page_id = int(request.args.get("page_id"))
    except (ValueError, TypeError):
        return jsonify(error="page_id must be provided in request query"), 400

    gen_email: GenEmail = GenEmail.get(alias_id)

    if gen_email.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    alias_logs = get_alias_log(gen_email, page_id)

    activities = []
    for alias_log in alias_logs:
        activity = {"timestamp": alias_log.when.timestamp}
        if alias_log.is_reply:
            activity["from"] = alias_log.alias
            activity["to"] = alias_log.website_from or alias_log.website_email
            activity["action"] = "reply"
        else:
            activity["to"] = alias_log.alias
            activity["from"] = alias_log.website_from or alias_log.website_email

            if alias_log.bounced:
                activity["action"] = "bounced"
            elif alias_log.blocked:
                activity["action"] = "block"
            else:
                activity["action"] = "forward"

        activities.append(activity)

    return jsonify(activities=activities), 200


@api_bp.route("/aliases/<int:alias_id>", methods=["PUT"])
@cross_origin()
@verify_api_key
def update_alias(alias_id):
    """
    Update alias note
    Input:
        alias_id: in url
        note: in body
    Output:
        200


    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    user = g.user
    gen_email: GenEmail = GenEmail.get(alias_id)

    if gen_email.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    new_note = data.get("note")
    gen_email.note = new_note
    db.session.commit()

    return jsonify(note=new_note), 200


def serialize_contact(fe: Contact) -> dict:

    res = {
        "creation_date": fe.created_at.format(),
        "creation_timestamp": fe.created_at.timestamp,
        "last_email_sent_date": None,
        "last_email_sent_timestamp": None,
        "contact": fe.website_from or fe.website_email,
        "reverse_alias": fe.website_send_to(),
    }

    fel: ForwardEmailLog = fe.last_reply()
    if fel:
        res["last_email_sent_date"] = fel.created_at.format()
        res["last_email_sent_timestamp"] = fel.created_at.timestamp

    return res


def get_alias_contacts(gen_email, page_id: int) -> [dict]:
    q = (
        Contact.query.filter_by(gen_email_id=gen_email.id)
        .order_by(Contact.id.desc())
        .limit(PAGE_LIMIT)
        .offset(page_id * PAGE_LIMIT)
    )

    res = []
    for fe in q.all():
        res.append(serialize_contact(fe))

    return res


@api_bp.route("/aliases/<int:alias_id>/contacts")
@cross_origin()
@verify_api_key
def get_alias_contacts_route(alias_id):
    """
    Get alias contacts
    Input:
        page_id: in query
    Output:
        - contacts: list of contacts:
            - creation_date
            - creation_timestamp
            - last_email_sent_date
            - last_email_sent_timestamp
            - contact
            - reverse_alias

    """
    user = g.user
    try:
        page_id = int(request.args.get("page_id"))
    except (ValueError, TypeError):
        return jsonify(error="page_id must be provided in request query"), 400

    gen_email: GenEmail = GenEmail.get(alias_id)

    if gen_email.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    contacts = get_alias_contacts(gen_email, page_id)

    return jsonify(contacts=contacts), 200


@api_bp.route("/aliases/<int:alias_id>/contacts", methods=["POST"])
@cross_origin()
@verify_api_key
def create_contact_route(alias_id):
    """
    Create contact for an alias
    Input:
        alias_id: in url
        contact: in body
    Output:
        201 if success
        409 if contact already added


    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    user = g.user
    gen_email: GenEmail = GenEmail.get(alias_id)

    if gen_email.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    contact_email = data.get("contact")

    # generate a reply_email, make sure it is unique
    # not use while to avoid infinite loop
    reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
    for _ in range(1000):
        reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
        if not Contact.get_by(reply_email=reply_email):
            break

    _, website_email = parseaddr(contact_email)

    # already been added
    if Contact.get_by(gen_email_id=gen_email.id, website_email=website_email):
        return jsonify(error="Contact already added"), 409

    contact = Contact.create(
        gen_email_id=gen_email.id,
        website_email=website_email,
        website_from=contact_email,
        reply_email=reply_email,
    )

    LOG.d("create reverse-alias for %s %s", contact_email, gen_email)
    db.session.commit()

    return jsonify(**serialize_contact(contact)), 201
