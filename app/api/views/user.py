from flask import jsonify, g

from app.api.base import api_bp, require_api_sudo, require_api_auth
from app.extensions import limiter
from app.models import ApiToCookieToken
from app.user_utils import soft_delete_user


@api_bp.route("/user", methods=["DELETE"])
@require_api_sudo
def delete_user():
    """
    Delete the user. Requires sudo mode.
    """
    soft_delete_user(g.user, "API")
    return jsonify(ok=True)


@api_bp.route("/user/cookie_token", methods=["GET"])
@require_api_auth
@limiter.limit("5/minute")
def get_api_session_token():
    """
    Get a temporary token to exchange it for a cookie based session
    Output:
        200 and a temporary random token
        {
            token: "asdli3ldq39h9hd3",
        }
    """
    if not g.api_key:
        return jsonify(ok=False), 401
    token = ApiToCookieToken.create(
        user=g.user,
        api_key_id=g.api_key.id,
        commit=True,
    )
    return jsonify({"token": token.code})
