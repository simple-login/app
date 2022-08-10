from flask import jsonify, g
from sqlalchemy_utils.types.arrow import arrow

from app.api.base import api_bp, require_api_sudo, require_api_auth
from app import config
from app.extensions import limiter
from app.log import LOG
from app.models import Job, ApiToCookieToken


@api_bp.route("/user", methods=["DELETE"])
@require_api_sudo
def delete_user():
    """
    Delete the user. Requires sudo mode.

    """
    # Schedule delete account job
    LOG.w("schedule delete account job for %s", g.user)
    Job.create(
        name=config.JOB_DELETE_ACCOUNT,
        payload={"user_id": g.user.id},
        run_at=arrow.now(),
        commit=True,
    )
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
    token = ApiToCookieToken.create(
        user=g.user,
        api_key_id=g.api_key.id,
        commit=True,
    )
    return jsonify({"token": token.code})
