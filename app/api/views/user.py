from flask import jsonify, g
from sqlalchemy_utils.types.arrow import arrow

from app.api.base import api_bp, require_api_sudo
from app import config
from app.log import LOG
from app.models import Job


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
