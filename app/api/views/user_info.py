from flask import jsonify, g

from app.api.base import api_bp, require_api_auth


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
