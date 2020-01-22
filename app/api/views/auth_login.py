from flask import g
from flask import jsonify, request
from flask_cors import cross_origin
from itsdangerous import Signer

from app.api.base import api_bp, verify_api_key
from app.config import EMAIL_DOMAIN, MAX_NB_EMAIL_FREE_PLAN, FLASK_SECRET
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, AliasUsedOn, User, ApiKey
from app.utils import convert_to_id


@api_bp.route("/auth/login", methods=["POST"])
@cross_origin()
def auth_login():
    """
    Authenticate user
    Input:
        email
        password
        device: to create an ApiKey associated with this device
    Output:
        200 and user info containing:
        {
            name: "John Wick",
            mfa_enabled: true,
            mfa_key: "a long string",
            api_key: "a long string"
        }

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    email = data.get("email")
    password = data.get("password")
    device = data.get("device")

    user = User.filter_by(email=email).first()

    if not user or not user.check_password(password):
        return jsonify(error="Email or password incorrect"), 400
    elif not user.activated:
        return jsonify(error="Account not activated"), 400

    ret = {
        "name": user.name,
        "mfa_enabled": user.enable_otp,
    }

    # do not give api_key, user can only obtain api_key after OTP verification
    if user.enable_otp:
        s = Signer(FLASK_SECRET)
        ret["mfa_key"] = s.sign(str(user.id))
        ret["api_key"] = ""
    else:
        api_key = ApiKey.create(user.id, device)
        db.session.commit()
        ret["mfa_key"] = ""
        ret["api_key"] = api_key.code

    return jsonify(**ret), 200
