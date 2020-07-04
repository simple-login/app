from flask import jsonify, g, request

from app.api.base import api_bp, require_api_auth
from app.extensions import db
from app.models import ApiKey


@api_bp.route("/user_info")
@require_api_auth
def user_info():
    """
    Return user info given the api-key
    """
    user = g.user

    return jsonify(
        {
            "name": user.name,
            "is_premium": user.is_premium(),
            "email": user.email,
            "in_trial": user.in_trial(),
        }
    )


@api_bp.route("/api_key", methods=["POST"])
@require_api_auth
def create_api_key():
    """Used to create a new api key
    Input:
    - device

    Output:
    - api_key
    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    device = data.get("device")

    api_key = ApiKey.create(user_id=g.user.id, name=device)
    db.session.commit()

    return jsonify(api_key=api_key.code), 201
