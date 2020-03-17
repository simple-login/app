from flask import jsonify, request, g
from flask_cors import cross_origin
from sqlalchemy import desc

from app.api.base import api_bp, verify_api_key
from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.log import LOG
from app.models import AliasUsedOn, Alias, User
from app.utils import convert_to_id, random_word


@api_bp.route("/user_info")
@cross_origin()
@verify_api_key
def user_info():
    """
    Return user info given the api-key
    """
    user = g.user

    return jsonify({"name": user.name, "is_premium": user.is_premium()})
