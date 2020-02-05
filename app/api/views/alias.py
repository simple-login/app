from flask import g
from flask import jsonify, request
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.dashboard.views.index import get_alias_info, AliasInfo
from app.extensions import db
from app.models import GenEmail


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

    """
    user = g.user
    try:
        page_id = int(request.args.get("page_id"))
    except (ValueError, TypeError):
        return jsonify(error="page_id must be provided in request query"), 400

    aliases: [AliasInfo] = get_alias_info(user.id, page_id=page_id)

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
