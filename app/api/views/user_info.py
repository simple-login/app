import base64
from io import BytesIO

from flask import jsonify, g, request, make_response
from flask_login import logout_user

from app import s3
from app.api.base import api_bp, require_api_auth
from app.config import SESSION_COOKIE_NAME
from app.extensions import db
from app.models import ApiKey, File, User
from app.utils import random_string


def user_to_dict(user: User) -> dict:
    ret = {
        "name": user.name,
        "is_premium": user.is_premium(),
        "email": user.email,
        "in_trial": user.in_trial(),
    }

    if user.profile_picture_id:
        ret["profile_picture_url"] = user.profile_picture.get_url()
    else:
        ret["profile_picture_url"] = None

    return ret


@api_bp.route("/user_info")
@require_api_auth
def user_info():
    """
    Return user info given the api-key
    """
    user = g.user

    return jsonify(user_to_dict(user))


@api_bp.route("/user_info", methods=["PATCH"])
@require_api_auth
def update_user_info():
    """
    Input
    - profile_picture (optional): base64 of the profile picture. Set to null to remove the profile picture
    - name (optional)

    """
    user = g.user
    data = request.get_json() or {}

    if "profile_picture" in data:
        if data["profile_picture"] is None:
            if user.profile_picture_id:
                file = user.profile_picture
                File.delete(file.id)
                s3.delete(file.path)

                user.profile_picture_id = None
        else:
            raw_data = base64.decodebytes(data["profile_picture"].encode())
            file_path = random_string(30)
            file = File.create(user_id=user.id, path=file_path)
            db.session.flush()
            s3.upload_from_bytesio(file_path, BytesIO(raw_data))
            user.profile_picture_id = file.id
            db.session.flush()

    if "name" in data:
        user.name = data["name"]

    db.session.commit()

    return jsonify(user_to_dict(user))


@api_bp.route("/api_key", methods=["POST"])
@require_api_auth
def create_api_key():
    """Used to create a new api key
    Input:
    - device

    Output:
    - api_key
    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    device = data.get("device")

    api_key = ApiKey.create(user_id=g.user.id, name=device)
    db.session.commit()

    return jsonify(api_key=api_key.code), 201


@api_bp.route("/logout", methods=["GET"])
@require_api_auth
def logout():
    """
    Log user out on the web, i.e. remove the cookie

    Output:
    - 200
    """
    logout_user()
    response = make_response(jsonify(msg="User is logged out"), 200)
    response.delete_cookie(SESSION_COOKIE_NAME)

    return response
