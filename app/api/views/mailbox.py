from smtplib import SMTPRecipientsRefused

from flask import g
from flask import jsonify
from flask import request

from app.api.base import api_bp, require_api_auth
from app.dashboard.views.mailbox import send_verification_email
from app.dashboard.views.mailbox_detail import verify_mailbox_change
from app.email_utils import (
    mailbox_already_used,
    email_can_be_used_as_mailbox,
)
from app.extensions import db
from app.models import Mailbox


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
    mailbox_email = request.get_json().get("email").lower().strip().replace(" ", "")

    if mailbox_already_used(mailbox_email, user):
        return jsonify(error=f"{mailbox_email} already used"), 400
    elif not email_can_be_used_as_mailbox(mailbox_email):
        return (
            jsonify(
                error=f"{mailbox_email} cannot be used. Please note a mailbox cannot "
                f"be a disposable email address"
            ),
            400,
        )
    else:
        new_mailbox = Mailbox.create(email=mailbox_email, user_id=user.id)
        db.session.commit()

        send_verification_email(user, new_mailbox)

        return (
            jsonify(mailbox_to_dict(new_mailbox)),
            201,
        )


@api_bp.route("/mailboxes/<mailbox_id>", methods=["DELETE"])
@require_api_auth
def delete_mailbox(mailbox_id):
    """
    Delete mailbox
    Input:
        mailbox_id: in url
    Output:
        200 if deleted successfully

    """
    user = g.user
    mailbox = Mailbox.get(mailbox_id)

    if not mailbox or mailbox.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    if mailbox.id == user.default_mailbox_id:
        return jsonify(error="You cannot delete the default mailbox"), 400

    Mailbox.delete(mailbox_id)
    db.session.commit()

    return jsonify(deleted=True), 200


@api_bp.route("/mailboxes/<mailbox_id>", methods=["PUT"])
@require_api_auth
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
        new_email = data.get("email").lower().strip()

        if mailbox_already_used(new_email, user):
            return jsonify(error=f"{new_email} already used"), 400
        elif not email_can_be_used_as_mailbox(new_email):
            return (
                jsonify(
                    error=f"{new_email} cannot be used. Please note a mailbox cannot "
                    f"be a disposable email address"
                ),
                400,
            )

        try:
            verify_mailbox_change(user, mailbox, new_email)
        except SMTPRecipientsRefused:
            return jsonify(error=f"Incorrect mailbox, please recheck {new_email}"), 400
        else:
            mailbox.new_email = new_email
            changed = True

    if "cancel_email_change" in data:
        cancel_email_change = data.get("cancel_email_change")
        if cancel_email_change:
            mailbox.new_email = None
            changed = True

    if changed:
        db.session.commit()

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

    for mailbox in Mailbox.query.filter_by(user_id=user.id):
        mailboxes.append(mailbox)

    return (
        jsonify(mailboxes=[mailbox_to_dict(mb) for mb in mailboxes]),
        200,
    )
