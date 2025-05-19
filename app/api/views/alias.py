from typing import Optional

from deprecated import deprecated
from flask import g
from flask import jsonify
from flask import request

from app import alias_utils, alias_delete
from app.alias_audit_log_utils import emit_alias_audit_log, AliasAuditLogAction
from app.alias_mailbox_utils import set_mailboxes_for_alias
from app.api.base import api_bp, require_api_auth
from app.api.serializer import (
    AliasInfo,
    serialize_alias_info,
    serialize_contact,
    get_alias_infos_with_pagination,
    get_alias_contacts,
    serialize_alias_info_v2,
    get_alias_info_v2,
    get_alias_infos_with_pagination_v3,
)
from app.dashboard.views.alias_contact_manager import create_contact
from app.dashboard.views.alias_log import get_alias_log
from app.db import Session
from app.errors import (
    CannotCreateContactForReverseAlias,
    ErrContactErrorUpgradeNeeded,
    ErrContactAlreadyExists,
    ErrAddressInvalid,
)
from app.extensions import limiter
from app.log import LOG
from app.models import Alias, Contact, Mailbox, AliasDeleteReason


@deprecated
@api_bp.route("/aliases", methods=["GET", "POST"])
@require_api_auth
@limiter.limit("10/minute", key_func=lambda: g.user.id)
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
@require_api_auth
@limiter.limit("50/minute", key_func=lambda: g.user.id)
def get_aliases_v2():
    """
    Get aliases
    Input:
        page_id: in query
        pinned: in query
        disabled: in query
        enabled: in query
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
            - mailbox
            - mailboxes
            - support_pgp
            - disable_pgp
            - latest_activity: null if no activity.
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

    pinned = "pinned" in request.args
    disabled = "disabled" in request.args
    enabled = "enabled" in request.args

    if pinned:
        alias_filter = "pinned"
    elif disabled:
        alias_filter = "disabled"
    elif enabled:
        alias_filter = "enabled"
    else:
        alias_filter = None

    query = None
    data = request.get_json(silent=True)
    if data:
        query = data.get("query")

    alias_infos: [AliasInfo] = get_alias_infos_with_pagination_v3(
        user, page_id=page_id, query=query, alias_filter=alias_filter
    )

    return (
        jsonify(
            aliases=[serialize_alias_info_v2(alias_info) for alias_info in alias_infos]
        ),
        200,
    )


@api_bp.route("/aliases/<int:alias_id>", methods=["DELETE"])
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

    if not alias or alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    LOG.i(f"User {user} is deleting alias {alias}")
    alias_delete.delete_alias(alias, user, AliasDeleteReason.ManualAction, commit=True)

    return jsonify(deleted=True), 200


@api_bp.route("/aliases/<int:alias_id>/toggle", methods=["POST"])
@require_api_auth
@limiter.limit("100/hour")
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

    if not alias or alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    alias_utils.change_alias_status(
        alias,
        enabled=not alias.enabled,
        message=f"Set enabled={not alias.enabled} via API",
    )
    LOG.i(f"User {user} changed alias {alias} enabled status to {alias.enabled}")
    Session.commit()

    return jsonify(enabled=alias.enabled), 200


@api_bp.route("/aliases/<int:alias_id>/activities")
@require_api_auth
@limiter.limit("30/minute")
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

    if not alias or alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    alias_logs = get_alias_log(alias, page_id)

    activities = []
    for alias_log in alias_logs:
        activity = {
            "timestamp": alias_log.when.timestamp,
            "reverse_alias": alias_log.reverse_alias,
            "reverse_alias_address": alias_log.contact.reply_email,
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


@api_bp.route("/aliases/<int:alias_id>", methods=["PUT", "PATCH"])
@require_api_auth
def update_alias(alias_id):
    """
    Update alias note
    Input:
        alias_id: in url
        note (optional): in body
        name (optional): in body
        mailbox_id (optional): in body
        disable_pgp (optional): in body
    Output:
        200
    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    user = g.user
    alias: Alias = Alias.get(alias_id)

    if not alias or alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    changed_fields = []
    changed = False
    if "note" in data:
        new_note = data.get("note")
        alias.note = new_note
        changed_fields.append("note")
        changed = True

    if "mailbox_id" in data:
        mailbox_id = int(data.get("mailbox_id"))
        mailbox = Mailbox.get(mailbox_id)
        if not mailbox or mailbox.user_id != user.id or not mailbox.verified:
            return jsonify(error="Forbidden"), 400

        alias.mailbox_id = mailbox_id
        changed_fields.append(f"mailbox_id ({mailbox_id})")
        changed = True

    if "mailbox_ids" in data:
        try:
            mailbox_ids = [int(m_id) for m_id in data.get("mailbox_ids")]
        except ValueError:
            return jsonify(error="Invalid mailbox_id"), 400
        err = set_mailboxes_for_alias(
            user_id=user.id, alias=alias, mailbox_ids=mailbox_ids
        )
        if err:
            return jsonify(error=err.value), 400

        mailbox_ids_string = ",".join(map(str, mailbox_ids))
        changed_fields.append(f"mailbox_ids ({mailbox_ids_string})")
        changed = True

    if "name" in data:
        # to make sure alias name doesn't contain linebreak
        new_name = data.get("name")
        if new_name and len(new_name) > 128:
            return jsonify(error="Name can't be longer than 128 characters"), 400

        if new_name:
            new_name = new_name.replace("\n", "")
        alias.name = new_name
        changed_fields.append("name")
        changed = True

    if "disable_pgp" in data:
        alias.disable_pgp = data.get("disable_pgp")
        changed_fields.append("disable_pgp")
        changed = True

    if "pinned" in data:
        alias.pinned = data.get("pinned")
        changed_fields.append("pinned")
        changed = True

    if changed:
        changed_fields_string = ",".join(changed_fields)
        emit_alias_audit_log(
            alias,
            AliasAuditLogAction.UpdateAlias,
            f"Alias fields updated ({changed_fields_string})",
        )
        Session.commit()

    return jsonify(ok=True), 200


@api_bp.route("/aliases/<int:alias_id>", methods=["GET"])
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

    if not alias:
        return jsonify(error="Unknown error"), 400

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    return jsonify(**serialize_alias_info_v2(get_alias_info_v2(alias))), 200


@api_bp.route("/aliases/<int:alias_id>/contacts")
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

    if not alias:
        return jsonify(error="No such alias"), 404

    if alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    contacts = get_alias_contacts(alias, page_id)

    return jsonify(contacts=contacts), 200


@api_bp.route("/aliases/<int:alias_id>/contacts", methods=["POST"])
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

    alias: Optional[Alias] = Alias.get_by(id=alias_id, user_id=g.user.id)
    if not alias:
        return jsonify(error="Forbidden"), 403

    contact_address = data.get("contact")

    try:
        contact = create_contact(alias, contact_address)
    except ErrContactErrorUpgradeNeeded as err:
        return jsonify(error=err.error_for_user()), 403
    except (ErrAddressInvalid, CannotCreateContactForReverseAlias) as err:
        return jsonify(error=err.error_for_user()), 400
    except ErrContactAlreadyExists as err:
        return jsonify(**serialize_contact(err.contact, existed=True)), 200

    return jsonify(**serialize_contact(contact)), 201


@api_bp.route("/contacts/<int:contact_id>", methods=["DELETE"])
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
    contact: Optional[Contact] = Contact.get(contact_id)

    if not contact or contact.alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    emit_alias_audit_log(
        alias=contact.alias,
        action=AliasAuditLogAction.DeleteContact,
        message=f"Deleted contact {contact_id} ({contact.email})",
    )
    Contact.delete(contact_id)
    Session.commit()

    return jsonify(deleted=True), 200


@api_bp.route("/contacts/<int:contact_id>/toggle", methods=["POST"])
@require_api_auth
def toggle_contact(contact_id):
    """
    Block/Unblock contact
    Input:
        contact_id: in url
    Output:
        200
    """
    user = g.user
    contact: Optional[Contact] = Contact.get(contact_id)

    if not contact or contact.alias.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    contact.block_forward = not contact.block_forward
    emit_alias_audit_log(
        alias=contact.alias,
        action=AliasAuditLogAction.UpdateContact,
        message=f"Set contact state {contact.id} {contact.email} -> {contact.website_email} to blocked {contact.block_forward}",
    )
    Session.commit()

    return jsonify(block_forward=contact.block_forward), 200
