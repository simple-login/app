from functools import wraps

import arrow
from flask import Blueprint, request, jsonify, g

from app.extensions import db
from app.models import ApiKey

api_bp = Blueprint(name="api", import_name=__name__, url_prefix="/api")


def verify_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_code = request.headers.get("Authentication")
        api_key = ApiKey.get_by(code=api_code)

        if not api_key:
            return jsonify(error="Wrong api key"), 401

        # Update api key stats
        api_key.last_used = arrow.now()
        api_key.times += 1
        db.session.commit()

        g.user = api_key.user

        return f(*args, **kwargs)

    return decorated
