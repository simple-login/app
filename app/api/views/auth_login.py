from flask import jsonify, request
import facebook
import google.oauth2.credentials
import googleapiclient.discovery
from flask import jsonify, request
from flask_cors import cross_origin
from itsdangerous import Signer

from app import email_utils
from app.api.base import api_bp
from app.config import (
    FLASK_SECRET,
    DISABLE_REGISTRATION,
)
from app.email_utils import can_be_used_as_personal_email, email_already_used
from app.extensions import db
from app.log import LOG
from app.models import User, ApiKey, SocialAuth


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

    return jsonify(**auth_payload(user, device)), 200


@api_bp.route("/auth/facebook", methods=["POST"])
@cross_origin()
def auth_facebook():
    """
    Authenticate user with Facebook
    Input:
        facebook_token: facebook access token
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

    facebook_token = data.get("facebook_token")
    device = data.get("device")

    graph = facebook.GraphAPI(access_token=facebook_token)
    user_info = graph.get_object("me", fields="email,name")
    email = user_info.get("email")

    user = User.get_by(email=email)

    if not user:
        if DISABLE_REGISTRATION:
            return jsonify(error="registration is closed"), 400
        if not can_be_used_as_personal_email(email) or email_already_used(email):
            return jsonify(error=f"cannot use {email} as personal inbox"), 400

        LOG.d("create facebook user with %s", user_info)
        user = User.create(email=email.lower(), name=user_info["name"], activated=True)
        db.session.commit()
        email_utils.send_welcome_email(user)

    if not SocialAuth.get_by(user_id=user.id, social="facebook"):
        SocialAuth.create(user_id=user.id, social="facebook")
        db.session.commit()

    return jsonify(**auth_payload(user, device)), 200


@api_bp.route("/auth/google", methods=["POST"])
@cross_origin()
def auth_google():
    """
    Authenticate user with Facebook
    Input:
        google_token: Google access token
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

    google_token = data.get("google_token")
    device = data.get("device")

    cred = google.oauth2.credentials.Credentials(token=google_token)

    build = googleapiclient.discovery.build("oauth2", "v2", credentials=cred)

    user_info = build.userinfo().get().execute()
    email = user_info.get("email")

    user = User.get_by(email=email)

    if not user:
        if DISABLE_REGISTRATION:
            return jsonify(error="registration is closed"), 400
        if not can_be_used_as_personal_email(email) or email_already_used(email):
            return jsonify(error=f"cannot use {email} as personal inbox"), 400

        LOG.d("create Google user with %s", user_info)
        user = User.create(email=email.lower(), name="", activated=True)
        db.session.commit()
        email_utils.send_welcome_email(user)

    if not SocialAuth.get_by(user_id=user.id, social="google"):
        SocialAuth.create(user_id=user.id, social="google")
        db.session.commit()

    return jsonify(**auth_payload(user, device)), 200


def auth_payload(user, device) -> dict:
    ret = {
        "name": user.name,
        "mfa_enabled": user.enable_otp,
    }

    # do not give api_key, user can only obtain api_key after OTP verification
    if user.enable_otp:
        s = Signer(FLASK_SECRET)
        ret["mfa_key"] = s.sign(str(user.id))
        ret["api_key"] = None
    else:
        api_key = ApiKey.get_by(user_id=user.id, name=device)
        if not api_key:
            LOG.d("create new api key for %s and %s", user, device)
            api_key = ApiKey.create(user.id, device)
            db.session.commit()
        ret["mfa_key"] = None
        ret["api_key"] = api_key.code

    return ret
