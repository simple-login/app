import base64
from io import BytesIO
from typing import Optional

from flask import jsonify, g, request, make_response

from app import s3, config
from app.api.base import api_bp, require_api_auth
from app.config import SESSION_COOKIE_NAME
from app.db import Session
from app.models import ApiKey, File, PartnerUser, User
from app.proton.utils import get_proton_partner
from app.session import logout_session
from app.utils import random_string


def get_connected_proton_address(user: User) -> Optional[str]:
    proton_partner = get_proton_partner()
    partner_user = PartnerUser.get_by(user_id=user.id, partner_id=proton_partner.id)
    if partner_user is None:
        return None
    return partner_user.partner_email


def user_to_dict(user: User) -> dict:
    ret = {
        "name": user.name or "",
        "is_premium": user.is_premium(),
        "email": user.email,
        "in_trial": user.in_trial(),
        "max_alias_free_plan": user.max_alias_for_free_account(),
        "connected_proton_address": None,
    }

    if config.CONNECT_WITH_PROTON:
        ret["connected_proton_address"] = get_connected_proton_address(user)

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

    Output as json
    - name
    - is_premium
    - email
    - in_trial
    - max_alias_free
    - is_connected_with_proton
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
                user.profile_picture_id = None
                Session.flush()
                if file:
                    File.delete(file.id)
                    s3.delete(file.path)
                    Session.flush()
        else:
            raw_data = base64.decodebytes(data["profile_picture"].encode())
            file_path = random_string(30)
            file = File.create(user_id=user.id, path=file_path)
            Session.flush()
            s3.upload_from_bytesio(file_path, BytesIO(raw_data))
            user.profile_picture_id = file.id
            Session.flush()

    if "name" in data:
        user.name = data["name"]

    Session.commit()

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
    Session.commit()

    return jsonify(api_key=api_key.code), 201


@api_bp.route("/logout", methods=["GET"])
@require_api_auth
def logout():
    """
    Log user out on the web, i.e. remove the cookie

    Output:
    - 200
    """
    logout_session()
    response = make_response(jsonify(msg="User is logged out"), 200)
    response.delete_cookie(SESSION_COOKIE_NAME)

    return response
