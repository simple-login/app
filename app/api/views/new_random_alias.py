from flask import g
from flask import jsonify, request
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.config import MAX_NB_EMAIL_FREE_PLAN
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, AliasUsedOn, AliasGeneratorEnum


@api_bp.route("/alias/random/new", methods=["POST"])
@cross_origin()
@verify_api_key
def new_random_alias():
    """
    Create a new random alias
    Output:
        201 if success

    """
    user = g.user
    if not user.can_create_new_alias():
        LOG.d("user %s cannot create new random alias", user)
        return (
            jsonify(
                error=f"You have reached the limitation of a free account with the maximum of "
                f"{MAX_NB_EMAIL_FREE_PLAN} aliases, please upgrade your plan to create more aliases"
            ),
            400,
        )

    scheme = user.alias_generator
    mode = request.args.get("mode")
    if mode:
        if mode == "word":
            scheme = AliasGeneratorEnum.word.value
        elif mode == "uuid":
            scheme = AliasGeneratorEnum.uuid.value
        else:
            return jsonify(error=f"{mode} must be either word or alias"), 400

    gen_email = GenEmail.create_new_random(user_id=user.id, scheme=scheme)
    db.session.commit()

    hostname = request.args.get("hostname")
    if hostname:
        AliasUsedOn.create(gen_email_id=gen_email.id, hostname=hostname)
        db.session.commit()

    return jsonify(alias=gen_email.email), 201
