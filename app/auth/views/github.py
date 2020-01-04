from flask import request, session, redirect, flash
from flask_login import login_user
from requests_oauthlib import OAuth2Session

from app import email_utils
from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
from app.config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, URL
from app.extensions import db
from app.log import LOG
from app.models import User
from app.utils import encode_url

_authorization_base_url = "https://github.com/login/oauth/authorize"
_token_url = "https://github.com/login/oauth/access_token"

# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
_redirect_uri = URL + "/auth/github/callback"


@auth_bp.route("/github/login")
def github_login():
    next_url = request.args.get("next")
    if next_url:
        redirect_uri = _redirect_uri + "?next=" + encode_url(next_url)
    else:
        redirect_uri = _redirect_uri

    github = OAuth2Session(
        GITHUB_CLIENT_ID, scope=["user:email"], redirect_uri=redirect_uri
    )
    authorization_url, state = github.authorization_url(_authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session["oauth_state"] = state
    return redirect(authorization_url)


@auth_bp.route("/github/callback")
def github_callback():
    # user clicks on cancel
    if "error" in request.args:
        flash("Please use another sign in method then", "warning")
        return redirect("/")

    github = OAuth2Session(
        GITHUB_CLIENT_ID,
        state=session["oauth_state"],
        scope=["user:email"],
        redirect_uri=_redirect_uri,
    )
    token = github.fetch_token(
        _token_url,
        client_secret=GITHUB_CLIENT_SECRET,
        authorization_response=request.url,
    )

    # a dict with "name", "login"
    github_user_data = github.get("https://api.github.com/user").json()
    LOG.d("user login with github %s", github_user_data)

    # return list of emails
    # {
    #     'email': 'abcd@gmail.com',
    #     'primary': False,
    #     'verified': True,
    #     'visibility': None
    # }
    emails = github.get("https://api.github.com/user/emails").json()

    # only take the primary email
    email = None

    for e in emails:
        if e.get("verified") and e.get("primary"):
            email = e.get("email")
            break

    if not email:
        raise Exception("cannot get email for github user")

    user = User.get_by(email=email)

    # create user
    if not user:
        LOG.d("create github user")
        user = User.create(
            email=email.lower(), name=github_user_data.get("name") or "", activated=True
        )
        db.session.commit()
        login_user(user)
        email_utils.send_welcome_email(user.email, user.name)

        flash(f"Welcome to SimpleLogin {user.name}!", "success")

    # The activation link contains the original page, for ex authorize page
    next_url = request.args.get("next") if request.args else None

    return after_login(user, next_url)
