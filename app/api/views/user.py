from flask import jsonify, g
from sqlalchemy_utils.types.arrow import arrow

from app.api.base import api_bp, require_api_sudo, require_api_auth
from app.constants import JobType
from app.extensions import limiter
from app.log import LOG
from app.models import Job, ApiToCookieToken
from app.user_audit_log_utils import (
    emit_user_marked_for_deletion_audit_log,
    USER_REQUESTED_DELETION_REASON,
)


@api_bp.route("/user", methods=["DELETE"])
@require_api_sudo
def delete_user():
    """
    Delete the user. Requires sudo mode.

    """
    # Schedule delete account job
    source = f"api key {g.api_key.id}" if g.api_key else "api (web session)"
    emit_user_marked_for_deletion_audit_log(
        user=g.user, source=source, reason=USER_REQUESTED_DELETION_REASON
    )
    LOG.w("schedule delete account job for %s", g.user)
    Job.create(
        name=JobType.DELETE_ACCOUNT.value,
        payload={
            "user_id": g.user.id,
            "source": source,
            "reason": USER_REQUESTED_DELETION_REASON,
        },
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
    if not g.api_key:
        return jsonify(ok=False), 401
    token = ApiToCookieToken.create(
        user=g.user,
        api_key_id=g.api_key.id,
        commit=True,
    )
    return jsonify({"token": token.code})
