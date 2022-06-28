from flask import jsonify, g, request
from sqlalchemy_utils.types.arrow import arrow

from app.api.base import api_bp, require_api_auth
from app.db import Session


@api_bp.route("/sudo", methods=["PATCH"])
@require_api_auth
def enter_sudo():
    """
    Enter sudo mode

    Input
    - password: user password to validate request to enter sudo mode
    """
    user = g.user
    data = request.get_json() or {}
    if "password" not in data:
        return jsonify(error="Invalid password"), 403
    if not user.check_password(data["password"]):
        return jsonify(error="Invalid password"), 403

    g.api_key.sudo_mode_at = arrow.now()
    Session.commit()

    return jsonify(ok=True)
