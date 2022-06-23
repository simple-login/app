from functools import wraps
from typing import Tuple, Optional

import arrow
from flask import Blueprint, request, jsonify, g
from flask_login import current_user

from app.db import Session
from app.models import ApiKey

api_bp = Blueprint(name="api", import_name=__name__, url_prefix="/api")

SUDO_MODE_MINUTES_VALID = 5


def authorize_request() -> Optional[Tuple[str, int]]:
    api_code = request.headers.get("Authentication")
    api_key = ApiKey.get_by(code=api_code)

    if not api_key:
        if current_user.is_authenticated:
            g.user = current_user
        else:
            return jsonify(error="Wrong api key"), 401
    else:
        # Update api key stats
        api_key.last_used = arrow.now()
        api_key.times += 1
        Session.commit()

        g.user = api_key.user

    if g.user.disabled:
        return jsonify(error="Disabled account"), 403

    g.api_key = api_key
    return None


def check_sudo_mode_is_active(api_key: ApiKey) -> bool:
    return api_key.sudo_mode_at and g.api_key.sudo_mode_at >= arrow.now().shift(
        minutes=-SUDO_MODE_MINUTES_VALID
    )


def require_api_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        error_return = authorize_request()
        if error_return:
            return error_return
        return f(*args, **kwargs)

    return decorated


def require_api_sudo(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        error_return = authorize_request()
        if error_return:
            return error_return
        if not check_sudo_mode_is_active(g.api_key):
            return jsonify(error="Need sudo"), 440
        return f(*args, **kwargs)

    return decorated
