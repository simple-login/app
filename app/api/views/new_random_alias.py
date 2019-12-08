from flask import g
from flask import jsonify, request
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, AliasUsedOn


# OBSOLETE
@api_bp.route("/alias/random/new", methods=["POST"])
@cross_origin()
@verify_api_key
def new_random_alias():
    """
    Create a new random alias
    Input:
        optional "hostname" in args
    Output:
        201 if success
        409 if alias already exists

    """
    LOG.error("/api/alias/new is obsolete! Called by %s", g.user)

    user = g.user
    if not user.can_create_new_random_alias():
        LOG.d("user %s cannot create random alias", user)
        return (
            jsonify(
                error="You have created 3 random aliases, please upgrade to create more"
            ),
            400,
        )

    hostname = request.args.get("hostname")
    gen_email = GenEmail.create_new_gen_email(user_id=user.id)
    db.session.commit()

    if hostname:
        AliasUsedOn.create(gen_email_id=gen_email.id, hostname=hostname)
        db.session.commit()

    return jsonify(alias=gen_email.email), 201
