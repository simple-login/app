from flask import g
from flask import jsonify
from flask import request
from flask_cors import cross_origin

from app.api.base import api_bp, require_api_auth
from app.api.serializer import (
    AliasInfo,
    serialize_alias_info,
    serialize_contact,
    get_alias_infos_with_pagination,
    get_alias_info,
    get_alias_contacts,
    get_alias_infos_with_pagination_v2,
    serialize_alias_info_v2,
)
from app.config import EMAIL_DOMAIN
from app.dashboard.views.alias_log import get_alias_log
from app.email_utils import parseaddr_unicode
from app.extensions import db
from app.log import LOG
from app.models import Alias, Contact, Mailbox
from app.utils import random_string


@api_bp.route("/aliases", methods=["GET", "POST"])
@cross_origin()
@require_api_auth
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

    query = None
    data = request.get_json(silent=True)
    if data:
        query = data.get("query")

    alias_infos: [AliasInfo] = get_alias_infos_with_pagination(
        user, page_id=page_id, query=query
    )

    return (
        jsonify(
            aliases=[serialize_alias_info(alias_info) for alias_info in alias_infos]
        ),
        200,
    )


@api_bp.route("/v2/aliases", methods=["GET", "POST"])
@cross_origin()
@require_api_auth
def get_aliases_v2():
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
            - (optional) latest_activity:
                - timestamp
                - action: forward|reply|block|bounced
                - contact:
                    - email
                    - name
                    - reverse_alias


    """
    user = g.user
    try:
        page_id = int(request.args.get("page_id"))
    except (ValueError, TypeError):
        return jsonify(error="page_id must be provided in request query"), 400

    query = None
    data = request.get_json(silent=True)
    if data:
        query = data.get("query")

    alias_infos: [AliasInfo] = get_alias_infos_with_pagination_v2(
        user, page_id=page_id, query=query
    )

    return (
        jsonify(
            aliases=[serialize_alias_info_v2(alias_info) for alias_info in alias_infos]
        ),
        200,
    )


@api_bp.route("/mailboxes", methods=["GET"])
@cross_origin()
@require_api_auth
def get_mailboxes():
    """
    Get mailboxes
    Output:
        - mailboxes: list of alias:
            - id
            - email
    """
    user = g.user

    return (
        jsonify(
            mailboxes=[{"id": mb.id, "email": mb.email} for mb in user.mailboxes()]
        ),
        200,
    )


@api_bp.route("/aliases/<int:alias_id>", methods=["DELETE"])
@cross_origin()
@require_api_auth
def delete_alias(alias_id):
    """
    Delete alias
    Input:
        alias_id: in url
    Output:
        200 if deleted successfully

    """
    user = g.user
    alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    Alias.delete(alias_id)
    db.session.commit()

    return jsonify(deleted=True), 200


@api_bp.route("/aliases/<int:alias_id>/toggle", methods=["POST"])
@cross_origin()
@require_api_auth
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
    alias: Alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    alias.enabled = not alias.enabled
    db.session.commit()

    return jsonify(enabled=alias.enabled), 200


@api_bp.route("/aliases/<int:alias_id>/activities")
@cross_origin()
@require_api_auth
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
            - action: forward|reply|block|bounced
            - reverse_alias

    """
    user = g.user
    try:
        page_id = int(request.args.get("page_id"))
    except (ValueError, TypeError):
        return jsonify(error="page_id must be provided in request query"), 400

    alias: Alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    alias_logs = get_alias_log(alias, page_id)

    activities = []
    for alias_log in alias_logs:
        activity = {
            "timestamp": alias_log.when.timestamp,
            "reverse_alias": alias_log.reverse_alias,
        }
        if alias_log.is_reply:
            activity["from"] = alias_log.alias
            activity["to"] = alias_log.website_email
            activity["action"] = "reply"
        else:
            activity["to"] = alias_log.alias
            activity["from"] = alias_log.website_email

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
@require_api_auth
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
    alias: Alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    changed = False
    if "note" in data:
        new_note = data.get("note")
        alias.note = new_note
        changed = True

    if "mailbox_id" in data:
        mailbox_id = int(data.get("mailbox_id"))
        mailbox = Mailbox.get(mailbox_id)
        if not mailbox or mailbox.user_id != user.id or not mailbox.verified:
            return jsonify(error="Forbidden"), 400

        alias.mailbox_id = mailbox_id
        changed = True

    if changed:
        db.session.commit()

    return jsonify(ok=True), 200


@api_bp.route("/aliases/<int:alias_id>", methods=["GET"])
@cross_origin()
@require_api_auth
def get_alias(alias_id):
    """
    Get alias
    Input:
        alias_id: in url
    Output:
        Alias info, same as in get_aliases

    """
    user = g.user
    alias: Alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    return jsonify(**serialize_alias_info(get_alias_info(alias))), 200


@api_bp.route("/aliases/<int:alias_id>/contacts")
@cross_origin()
@require_api_auth
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

    alias: Alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    contacts = get_alias_contacts(alias, page_id)

    return jsonify(contacts=contacts), 200


@api_bp.route("/aliases/<int:alias_id>/contacts", methods=["POST"])
@cross_origin()
@require_api_auth
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
    alias: Alias = Alias.get(alias_id)

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    contact_addr = data.get("contact")

    # generate a reply_email, make sure it is unique
    # not use while to avoid infinite loop
    reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
    for _ in range(1000):
        reply_email = f"ra+{random_string(25)}@{EMAIL_DOMAIN}"
        if not Contact.get_by(reply_email=reply_email):
            break

    contact_name, contact_email = parseaddr_unicode(contact_addr)

    # already been added
    if Contact.get_by(alias_id=alias.id, website_email=contact_email):
        return jsonify(error="Contact already added"), 409

    contact = Contact.create(
        user_id=alias.user_id,
        alias_id=alias.id,
        website_email=contact_email,
        name=contact_name,
        reply_email=reply_email,
    )

    LOG.d("create reverse-alias for %s %s", contact_addr, alias)
    db.session.commit()

    return jsonify(**serialize_contact(contact)), 201


@api_bp.route("/contacts/<int:contact_id>", methods=["DELETE"])
@cross_origin()
@require_api_auth
def delete_contact(contact_id):
    """
    Delete contact
    Input:
        contact_id: in url
    Output:
        200
    """
    user = g.user
    contact = Contact.get(contact_id)

    if not contact or contact.alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    Contact.delete(contact_id)
    db.session.commit()

    return jsonify(deleted=True), 200
