from flask import request, session, redirect, url_for, flash
from requests_oauthlib import OAuth2Session
from requests_oauthlib.compliance_fixes import facebook_compliance_fix

from app.auth.base import auth_bp
from app.auth.views.google import create_file_from_url
from app.config import (
    URL,
    FACEBOOK_CLIENT_ID,
    FACEBOOK_CLIENT_SECRET,
)
from app.db import Session
from app.log import LOG
from app.models import User, SocialAuth
from .login_utils import after_login
from ...utils import sanitize_email, sanitize_next_url

_authorization_base_url = "https://www.facebook.com/dialog/oauth"
_token_url = "https://graph.facebook.com/oauth/access_token"

_scope = ["email"]

# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
_redirect_uri = URL + "/auth/facebook/callback"


@auth_bp.route("/facebook/login")
def facebook_login():
    # to avoid flask-login displaying the login error message
    session.pop("_flashes", None)

    next_url = sanitize_next_url(request.args.get("next"))

    # Facebook does not allow to append param to redirect_uri
    # we need to pass the next url by session
    if next_url:
        session["facebook_next_url"] = next_url

    facebook = OAuth2Session(
        FACEBOOK_CLIENT_ID, scope=_scope, redirect_uri=_redirect_uri
    )
    facebook = facebook_compliance_fix(facebook)
    authorization_url, state = facebook.authorization_url(_authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session["oauth_state"] = state
    return redirect(authorization_url)


@auth_bp.route("/facebook/callback")
def facebook_callback():
    # user clicks on cancel
    if "error" in request.args:
        flash("Please use another sign in method then", "warning")
        return redirect("/")

    facebook = OAuth2Session(
        FACEBOOK_CLIENT_ID,
        state=session["oauth_state"],
        scope=_scope,
        redirect_uri=_redirect_uri,
    )
    facebook = facebook_compliance_fix(facebook)
    facebook.fetch_token(
        _token_url,
        client_secret=FACEBOOK_CLIENT_SECRET,
        authorization_response=request.url,
    )

    # Fetch a protected resource, i.e. user profile
    # {
    #     "email": "abcd@gmail.com",
    #     "id": "1234",
    #     "name": "First Last",
    #     "picture": {
    #         "data": {
    #             "url": "long_url"
    #         }
    #     }
    # }
    facebook_user_data = facebook.get(
        "https://graph.facebook.com/me?fields=id,name,email,picture{url}"
    ).json()

    email = facebook_user_data.get("email")

    # user choose to not share email, cannot continue
    if not email:
        flash(
            "In order to use SimpleLogin, you need to give us a valid email", "warning"
        )
        return redirect(url_for("auth.register"))

    email = sanitize_email(email)
    user = User.get_by(email=email)

    picture_url = facebook_user_data.get("picture", {}).get("data", {}).get("url")

    if user:
        if picture_url and not user.profile_picture_id:
            LOG.d("set user profile picture to %s", picture_url)
            file = create_file_from_url(user, picture_url)
            user.profile_picture_id = file.id
            Session.commit()

    else:
        flash(
            "Sorry you cannot sign up via Facebook, please use email/password sign-up instead",
            "error",
        )
        return redirect(url_for("auth.register"))

    next_url = None
    # The activation link contains the original page, for ex authorize page
    if "facebook_next_url" in session:
        next_url = session["facebook_next_url"]
        LOG.d("redirect user to %s", next_url)

        # reset the next_url to avoid user getting redirected at each login :)
        session.pop("facebook_next_url", None)

    if not SocialAuth.get_by(user_id=user.id, social="facebook"):
        SocialAuth.create(user_id=user.id, social="facebook")
        Session.commit()

    return after_login(user, next_url)
