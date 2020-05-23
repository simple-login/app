from flask import g
from flask import jsonify
from flask import request
from flask_cors import cross_origin

from app.api.base import api_bp, require_api_auth
from app.dashboard.views.mailbox import send_verification_email
from app.email_utils import (
    mailbox_already_used,
    email_domain_can_be_used_as_mailbox,
)
from app.extensions import db
from app.models import Mailbox


@api_bp.route("/mailboxes", methods=["POST"])
@cross_origin()
@require_api_auth
def create_mailbox():
    """
    Create a new mailbox. User needs to verify the mailbox via an activation email.
    Input:
        email: in body
    Output:
        the new mailbox
        - id
        - email
        - verified

    """
    user = g.user
    mailbox_email = request.get_json().get("email").lower().strip()

    if mailbox_already_used(mailbox_email, user):
        return jsonify(error=f"{mailbox_email} already used"), 400
    elif not email_domain_can_be_used_as_mailbox(mailbox_email):
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
            jsonify(
                id=new_mailbox.id,
                email=new_mailbox.email,
                verified=new_mailbox.verified,
                default=user.default_mailbox_id == new_mailbox.id,
            ),
            201,
        )
