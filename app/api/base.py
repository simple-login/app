from functools import wraps

import arrow
from flask import Blueprint, request, jsonify, g
from flask_login import current_user

from app.extensions import db
from app.models import ApiKey

api_bp = Blueprint(name="api", import_name=__name__, url_prefix="/api")


def require_api_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_code = request.headers.get("Authentication")
        api_key = ApiKey.get_by(code=api_code)

        if not api_key:
            # if user is authenticated, the request is authorized
            if current_user.is_authenticated:
                g.user = current_user
            else:
                return jsonify(error="Wrong api key"), 401
        else:
            # Update api key stats
            api_key.last_used = arrow.now()
            api_key.times += 1
            db.session.commit()

            g.user = api_key.user

        return f(*args, **kwargs)

    return decorated
