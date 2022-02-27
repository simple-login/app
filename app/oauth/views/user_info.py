from flask import request, jsonify
from flask_cors import cross_origin

from app.db import Session
from app.log import LOG
from app.models import OauthToken, ClientUser
from app.oauth.base import oauth_bp


@oauth_bp.route("/user_info")
@oauth_bp.route("/me")
@oauth_bp.route("/userinfo")
@cross_origin()
def user_info():
    """
    Call by client to get user information
    Usually bearer token is used.
    """
    if "AUTHORIZATION" in request.headers:
        access_token = request.headers["AUTHORIZATION"].replace("Bearer ", "")
    else:
        access_token = request.args.get("access_token")

    oauth_token: OauthToken = OauthToken.get_by(access_token=access_token)
    if not oauth_token:
        return jsonify(error="Invalid access token"), 400
    elif oauth_token.is_expired():
        LOG.d("delete oauth token %s", oauth_token)
        OauthToken.delete(oauth_token.id)
        Session.commit()
        return jsonify(error="Expired access token"), 400

    client_user = ClientUser.get_or_create(
        client_id=oauth_token.client_id, user_id=oauth_token.user_id
    )

    return jsonify(client_user.get_user_info())
