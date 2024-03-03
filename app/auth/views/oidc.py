from flask import request, session, redirect, flash, url_for
from requests_oauthlib import OAuth2Session

from app import config
from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
from app.config import (
    URL,
    OIDC_AUTHORIZATION_URL,
    OIDC_USER_INFO_URL,
    OIDC_TOKEN_URL,
    OIDC_SCOPES,
    OIDC_NAME_FIELD,
)
from app.db import Session
from app.email_utils import send_welcome_email
from app.log import LOG
from app.models import User, SocialAuth
from app.utils import encode_url, sanitize_email, sanitize_next_url


# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
_redirect_uri = URL + "/auth/oidc/callback"

SESSION_STATE_KEY = "oauth_state"


@auth_bp.route("/oidc/login")
def oidc_login():
    if config.OIDC_CLIENT_ID is None or config.OIDC_CLIENT_SECRET is None:
        return redirect(url_for("auth.login"))

    next_url = sanitize_next_url(request.args.get("next"))
    if next_url:
        redirect_uri = _redirect_uri + "?next=" + encode_url(next_url)
    else:
        redirect_uri = _redirect_uri

    oidc = OAuth2Session(
        config.OIDC_CLIENT_ID, scope=[OIDC_SCOPES], redirect_uri=redirect_uri
    )
    authorization_url, state = oidc.authorization_url(OIDC_AUTHORIZATION_URL)

    # State is used to prevent CSRF, keep this for later.
    session[SESSION_STATE_KEY] = state
    return redirect(authorization_url)


@auth_bp.route("/oidc/callback")
def oidc_callback():
    if SESSION_STATE_KEY not in session:
        flash("Invalid state, please retry", "error")
        return redirect(url_for("auth.login"))
    if config.OIDC_CLIENT_ID is None or config.OIDC_CLIENT_SECRET is None:
        return redirect(url_for("auth.login"))

    # user clicks on cancel
    if "error" in request.args:
        flash("Please use another sign in method then", "warning")
        return redirect("/")

    oidc = OAuth2Session(
        config.OIDC_CLIENT_ID,
        state=session[SESSION_STATE_KEY],
        scope=[OIDC_SCOPES],
        redirect_uri=_redirect_uri,
    )
    oidc.fetch_token(
        OIDC_TOKEN_URL,
        client_secret=config.OIDC_CLIENT_SECRET,
        authorization_response=request.url,
    )

    oidc_user_data = oidc.get(OIDC_USER_INFO_URL)
    if oidc_user_data.status_code != 200:
        LOG.e(
            f"cannot get oidc user data {oidc_user_data.status_code} {oidc_user_data.text}"
        )
        flash(
            "Cannot get user data from OIDC, please use another way to login/sign up",
            "error",
        )
        return redirect(url_for("auth.login"))
    oidc_user_data = oidc_user_data.json()

    email = oidc_user_data.get("email")

    if not email:
        LOG.e(f"cannot get email for OIDC user {oidc_user_data} {email}")
        flash(
            "Cannot get a valid email from OIDC, please another way to login/sign up",
            "error",
        )
        return redirect(url_for("auth.login"))

    email = sanitize_email(email)
    user = User.get_by(email=email)

    if not user and config.DISABLE_REGISTRATION:
        flash(
            "Sorry you cannot sign up via the OIDC provider. Please sign-up first with your email.",
            "error",
        )
        return redirect(url_for("auth.register"))
    elif not user:
        user = create_user(email, oidc_user_data)

    if not SocialAuth.get_by(user_id=user.id, social="oidc"):
        SocialAuth.create(user_id=user.id, social="oidc")
        Session.commit()

    # The activation link contains the original page, for ex authorize page
    next_url = sanitize_next_url(request.args.get("next")) if request.args else None

    return after_login(user, next_url)


def create_user(email, oidc_user_data):
    new_user = User.create(
        email=email,
        name=oidc_user_data.get(OIDC_NAME_FIELD),
        password="",
        activated=True,
    )
    LOG.i(f"Created new user for login request from OIDC. New user {new_user.id}")
    Session.commit()

    send_welcome_email(new_user)

    return new_user
