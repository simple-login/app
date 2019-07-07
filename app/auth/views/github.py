import arrow
from flask import request, session, redirect, url_for, flash
from flask_login import login_user
from requests_oauthlib import OAuth2Session

from app.auth.base import auth_bp
from app.config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, URL
from app.email_utils import notify_admin
from app.extensions import db
from app.log import LOG
from app.models import User
from app.utils import random_string

authorization_base_url = "https://github.com/login/oauth/authorize"
token_url = "https://github.com/login/oauth/access_token"

# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
redirect_uri = URL + "/github/callback"


@auth_bp.route("/github/login")
def github_login():
    github = OAuth2Session(
        GITHUB_CLIENT_ID, scope=["user:email"], redirect_uri=redirect_uri
    )
    authorization_url, state = github.authorization_url(authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session["oauth_state"] = state
    return redirect(authorization_url)


@auth_bp.route("/github/callback")
def github_callback():
    github = OAuth2Session(
        GITHUB_CLIENT_ID,
        state=session["oauth_state"],
        scope=["user:email"],
        redirect_uri=redirect_uri,
    )
    token = github.fetch_token(
        token_url,
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

    if user:
        login_user(user)
    # create user
    else:
        LOG.d("create github user")
        user = User.create(email=email, name=github_user_data["name"])

        # set a random password
        user.set_password(random_string(20))

        user.activated = True

        db.session.commit()
        login_user(user)

        flash(f"Welcome to SimpleLogin {user.name}!", "success")

        notify_admin(
            f"new user signs up {user.email}", f"{user.name} signs up at {arrow.now()}"
        )

    # The activation link contains the original page, for ex authorize page
    if "next" in request.args:
        next_url = request.args.get("next")
        LOG.debug("redirect user to %s", next_url)
        return redirect(next_url)
    else:
        LOG.debug("redirect user to dashboard")
        return redirect(url_for("dashboard.index"))
