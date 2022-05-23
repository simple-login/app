import requests
from flask import request, session, redirect, flash, url_for
from flask_limiter.util import get_remote_address
from flask_login import current_user
from requests_oauthlib import OAuth2Session

from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
from app.config import (
    PROTON_BASE_URL,
    PROTON_CLIENT_ID,
    PROTON_CLIENT_SECRET,
    PROTON_VALIDATE_CERTS,
    URL,
)
from app.proton.proton_client import HttpProtonClient, convert_access_token
from app.proton.proton_callback_handler import (
    ProtonCallbackHandler,
    Action,
    get_proton_partner,
)
from app.utils import sanitize_next_url

_authorization_base_url = PROTON_BASE_URL + "/oauth/authorize"
_token_url = PROTON_BASE_URL + "/oauth/token"

# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
_redirect_uri = URL + "/auth/proton/callback"


def extract_action() -> Action:
    action = request.args.get("action")
    if action is not None:
        if action == "link":
            return Action.Link
        else:
            raise Exception(f"Unknown action: {action}")
    return Action.Login


def get_action_from_state() -> Action:
    oauth_action = session["oauth_action"]
    if oauth_action == Action.Login.value:
        return Action.Login
    elif oauth_action == Action.Link.value:
        return Action.Link
    raise Exception(f"Unknown action in state: {oauth_action}")


@auth_bp.route("/proton/login")
def proton_login():
    if PROTON_CLIENT_ID is None or PROTON_CLIENT_SECRET is None:
        return redirect(url_for("auth.login"))

    next_url = sanitize_next_url(request.args.get("next"))
    if next_url:
        session["oauth_next"] = next_url
    proton = OAuth2Session(PROTON_CLIENT_ID, redirect_uri=_redirect_uri)
    authorization_url, state = proton.authorization_url(_authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session["oauth_state"] = state
    session["oauth_action"] = extract_action().value
    return redirect(authorization_url)


@auth_bp.route("/proton/callback")
def proton_callback():
    if PROTON_CLIENT_ID is None or PROTON_CLIENT_SECRET is None:
        return redirect(url_for("auth.login"))

    # user clicks on cancel
    if "error" in request.args:
        flash("Please use another sign in method then", "warning")
        return redirect("/")

    proton = OAuth2Session(
        PROTON_CLIENT_ID,
        state=session["oauth_state"],
        redirect_uri=_redirect_uri,
    )

    def check_status_code(response: requests.Response) -> requests.Response:
        if response.status_code != 200:
            raise Exception(
                f"Bad Proton API response [status={response.status_code}]: {response.json()}"
            )
        return response

    proton.register_compliance_hook("access_token_response", check_status_code)
    token = proton.fetch_token(
        _token_url,
        client_secret=PROTON_CLIENT_SECRET,
        authorization_response=request.url,
        verify=PROTON_VALIDATE_CERTS,
        method="GET",
        include_client_id=True,
    )
    credentials = convert_access_token(token["access_token"])
    action = get_action_from_state()

    proton_client = HttpProtonClient(
        PROTON_BASE_URL, credentials, get_remote_address(), verify=PROTON_VALIDATE_CERTS
    )
    handler = ProtonCallbackHandler(proton_client)
    proton_partner = get_proton_partner()

    if action == Action.Login:
        res = handler.handle_login(proton_partner)
    elif action == Action.Link:
        res = handler.handle_link(current_user, proton_partner)
    else:
        raise Exception(f"Unknown Action: {action.name}")

    if res.flash_message is not None:
        flash(res.flash_message, res.flash_category)

    if res.redirect_to_login:
        return redirect(url_for("auth.login"))

    if res.redirect:
        return redirect(res.redirect)

    next_url = session.get("oauth_next")
    return after_login(res.user, next_url)
