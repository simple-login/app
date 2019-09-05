import arrow
from flask import request, session, redirect, url_for, flash
from flask_login import login_user
from requests_oauthlib import OAuth2Session
from requests_oauthlib.compliance_fixes import facebook_compliance_fix

from app.auth.base import auth_bp
from app.auth.views.google import create_file_from_url
from app.config import URL, FACEBOOK_CLIENT_ID, FACEBOOK_CLIENT_SECRET
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import User
from app.utils import random_string

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

    next_url = request.args.get("next")

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
        flash("please use another sign in method then", "warning")
        return redirect("/")

    facebook = OAuth2Session(
        FACEBOOK_CLIENT_ID,
        state=session["oauth_state"],
        scope=_scope,
        redirect_uri=_redirect_uri,
    )
    facebook = facebook_compliance_fix(facebook)
    token = facebook.fetch_token(
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

    email = facebook_user_data["email"]
    user = User.get_by(email=email)

    picture_url = facebook_user_data.get("picture", {}).get("data", {}).get("url")

    if user:
        if picture_url and not user.profile_picture_id:
            LOG.d("set user profile picture to %s", picture_url)
            file = create_file_from_url(picture_url)
            user.profile_picture_id = file.id
            db.session.commit()

        login_user(user)
    # create user
    else:
        LOG.d("create facebook user with %s", facebook_user_data)
        user = User.create(email=email, name=facebook_user_data["name"], activated=True)

        if picture_url:
            LOG.d("set user profile picture to %s", picture_url)
            file = create_file_from_url(picture_url)
            user.profile_picture_id = file.id

        db.session.commit()
        login_user(user)

        flash(f"Welcome to SimpleLogin {user.name}!", "success")

        notify_admin(
            f"new user {user.name} {user.email} signs up via facebook",
            html_content=f"""
name: {user.name} <br>
email: {user.email} <br>
        """,
        )

    # The activation link contains the original page, for ex authorize page
    if "facebook_next_url" in session:
        next_url = session["facebook_next_url"]
        LOG.debug("redirect user to %s", next_url)

        # reset the next_url to avoid user getting redirected at each login :)
        session.pop("facebook_next_url", None)

        return redirect(next_url)
    else:
        LOG.debug("redirect user to dashboard")
        return redirect(url_for("dashboard.index"))
