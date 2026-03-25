from smtplib import SMTPRecipientsRefused

from flask import g
from flask import jsonify
from flask import request

from app import mailbox_utils
from app.api.base import api_bp, require_api_auth
from app.db import Session
from app.extensions import limiter
from app.models import Mailbox
from app.utils import sanitize_email


def mailbox_to_dict(mailbox: Mailbox):
    return {
        "id": mailbox.id,
        "email": mailbox.email,
        "verified": mailbox.verified,
        "default": mailbox.user.default_mailbox_id == mailbox.id,
        "creation_timestamp": mailbox.created_at.timestamp,
        "nb_alias": mailbox.nb_alias(),
    }


@api_bp.route("/mailboxes", methods=["POST"])
@limiter.limit("20/hour")
@require_api_auth
def create_mailbox():
    """
    Create a new mailbox. User needs to verify the mailbox via an activation email.
    Input:
        email: in body
    Output:
        the new mailbox dict
    """
    user = g.user
    email = request.get_json().get("email")
    if not email:
        return jsonify(error="Invalid email"), 400

    mailbox_email = sanitize_email(email)

    try:
        new_mailbox = mailbox_utils.create_mailbox(user, mailbox_email).mailbox
    except mailbox_utils.MailboxError as e:
        return jsonify(error=e.msg), 400

    return (
        jsonify(mailbox_to_dict(new_mailbox)),
        201,
    )


@api_bp.route("/mailboxes/<int:mailbox_id>", methods=["DELETE"])
@limiter.limit("100/hour")
@require_api_auth
def delete_mailbox(mailbox_id):
    """
    Delete mailbox
    Input:
        mailbox_id: in url
        (optional) transfer_aliases_to: in body. Id of the new mailbox for the aliases.
                                        If omitted or the value is set to -1,
                                        the aliases of the mailbox will be deleted too.
    Output:
        200 if deleted successfully

    """
    user = g.user
    mailbox = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    if mailbox.is_admin_disabled():
        return (
            jsonify(
                error="This mailbox has been disabled and cannot be deleted. Please contact support."
            ),
            400,
        )

    data = request.get_json() or {}
    transfer_mailbox_id = data.get("transfer_aliases_to")
    if transfer_mailbox_id and int(transfer_mailbox_id) >= 0:
        transfer_mailbox_id = int(transfer_mailbox_id)
    else:
        transfer_mailbox_id = None

    try:
        mailbox_utils.delete_mailbox(user, mailbox_id, transfer_mailbox_id)
    except mailbox_utils.MailboxError as e:
        return jsonify(error=e.msg), 400

    return jsonify(deleted=True), 200


@api_bp.route("/mailboxes/<int:mailbox_id>", methods=["PUT"])
@require_api_auth
@limiter.limit("100/hour")
def update_mailbox(mailbox_id):
    """
    Update mailbox
    Input:
        mailbox_id: in url
        (optional) default: in body. Set a mailbox as the default mailbox.
        (optional) email: in body. Change a mailbox email.
        (optional) cancel_email_change: in body. Cancel mailbox email change.
    Output:
        200 if updated successfully

    """
    user = g.user
    mailbox = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    if mailbox.is_admin_disabled():
        return (
            jsonify(error="This mailbox has been disabled. Please contact support."),
            400,
        )

    data = request.get_json() or {}
    changed = False
    if "default" in data:
        is_default = data.get("default")
        if is_default:
            if not mailbox.verified:
                return (
                    jsonify(
                        error="Unverified mailbox cannot be used as default mailbox"
                    ),
                    400,
                )
            user.default_mailbox_id = mailbox.id
            changed = True

    if "email" in data:
        new_email = sanitize_email(data.get("email"))
        try:
            mailbox_utils.request_mailbox_email_change(user, mailbox, new_email)
        except mailbox_utils.MailboxError as e:
            return jsonify(error=e.msg), 400
        except SMTPRecipientsRefused:
            return jsonify(error=f"Incorrect mailbox, please recheck {new_email}"), 400
        else:
            mailbox.new_email = new_email
            changed = True

    if "cancel_email_change" in data:
        cancel_email_change = data.get("cancel_email_change")
        if cancel_email_change:
            mailbox_utils.cancel_email_change(mailbox.id, user)
            changed = True

    if changed:
        Session.commit()

    return jsonify(updated=True), 200


@api_bp.route("/mailboxes", methods=["GET"])
@require_api_auth
def get_mailboxes():
    """
    Get verified mailboxes
    Output:
        - mailboxes: list of mailbox dict
    """
    user = g.user

    return (
        jsonify(mailboxes=[mailbox_to_dict(mb) for mb in user.mailboxes()]),
        200,
    )


@api_bp.route("/v2/mailboxes", methods=["GET"])
@require_api_auth
def get_mailboxes_v2():
    """
    Get all mailboxes - including unverified mailboxes
    Output:
        - mailboxes: list of mailbox dict
    """
    user = g.user
    mailboxes = []

    for mailbox in Mailbox.filter_by(user_id=user.id):
        mailboxes.append(mailbox)

    return (
        jsonify(mailboxes=[mailbox_to_dict(mb) for mb in mailboxes]),
        200,
    )
