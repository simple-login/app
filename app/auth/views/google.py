from flask import request, session, redirect, flash, url_for
from requests_oauthlib import OAuth2Session

from app import s3
from app.auth.base import auth_bp
from app.config import URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from app.db import Session
from app.log import LOG
from app.models import User, File, SocialAuth
from app.utils import random_string, sanitize_email
from .login_utils import after_login

_authorization_base_url = "https://accounts.google.com/o/oauth2/v2/auth"
_token_url = "https://www.googleapis.com/oauth2/v4/token"

_scope = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
]

# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
_redirect_uri = URL + "/auth/google/callback"


@auth_bp.route("/google/login")
def google_login():
    # to avoid flask-login displaying the login error message
    session.pop("_flashes", None)

    next_url = request.args.get("next")

    # Google does not allow to append param to redirect_url
    # we need to pass the next url by session
    if next_url:
        session["google_next_url"] = next_url

    google = OAuth2Session(GOOGLE_CLIENT_ID, scope=_scope, redirect_uri=_redirect_uri)
    authorization_url, state = google.authorization_url(_authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session["oauth_state"] = state
    return redirect(authorization_url)


@auth_bp.route("/google/callback")
def google_callback():
    # user clicks on cancel
    if "error" in request.args:
        flash("please use another sign in method then", "warning")
        return redirect("/")

    google = OAuth2Session(
        GOOGLE_CLIENT_ID,
        # some how Google Login fails with oauth_state KeyError
        # state=session["oauth_state"],
        scope=_scope,
        redirect_uri=_redirect_uri,
    )
    google.fetch_token(
        _token_url,
        client_secret=GOOGLE_CLIENT_SECRET,
        authorization_response=request.url,
    )

    # Fetch a protected resource, i.e. user profile
    # {
    #     "email": "abcd@gmail.com",
    #     "family_name": "First name",
    #     "given_name": "Last name",
    #     "id": "1234",
    #     "locale": "en",
    #     "name": "First Last",
    #     "picture": "http://profile.jpg",
    #     "verified_email": true
    # }
    google_user_data = google.get(
        "https://www.googleapis.com/oauth2/v1/userinfo"
    ).json()

    email = sanitize_email(google_user_data["email"])
    user = User.get_by(email=email)

    picture_url = google_user_data.get("picture")

    if user:
        if picture_url and not user.profile_picture_id:
            LOG.d("set user profile picture to %s", picture_url)
            file = create_file_from_url(user, picture_url)
            user.profile_picture_id = file.id
            Session.commit()
    else:
        flash(
            "Sorry you cannot sign up via Google, please use email/password sign-up instead",
            "error",
        )
        return redirect(url_for("auth.register"))

    next_url = None
    # The activation link contains the original page, for ex authorize page
    if "google_next_url" in session:
        next_url = session["google_next_url"]
        LOG.d("redirect user to %s", next_url)

        # reset the next_url to avoid user getting redirected at each login :)
        session.pop("google_next_url", None)

    if not SocialAuth.get_by(user_id=user.id, social="google"):
        SocialAuth.create(user_id=user.id, social="google")
        Session.commit()

    return after_login(user, next_url)


def create_file_from_url(user, url) -> File:
    file_path = random_string(30)
    file = File.create(path=file_path, user_id=user.id)

    s3.upload_from_url(url, file_path)

    Session.flush()
    LOG.d("upload file %s to s3", file)

    return file
