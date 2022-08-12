import requests
from flask import request, session, redirect, flash, url_for
from flask_limiter.util import get_remote_address
from flask_login import current_user
from requests_oauthlib import OAuth2Session
from typing import Optional

from app.auth.base import auth_bp
from app.auth.views.login_utils import after_login
from app.config import (
    PROTON_BASE_URL,
    PROTON_CLIENT_ID,
    PROTON_CLIENT_SECRET,
    PROTON_EXTRA_HEADER_NAME,
    PROTON_EXTRA_HEADER_VALUE,
    PROTON_VALIDATE_CERTS,
    URL,
)
from app.log import LOG
from app.models import ApiKey, User
from app.proton.proton_client import HttpProtonClient, convert_access_token
from app.proton.proton_callback_handler import (
    ProtonCallbackHandler,
    Action,
)
from app.proton.utils import get_proton_partner
from app.utils import sanitize_next_url, sanitize_scheme

_authorization_base_url = PROTON_BASE_URL + "/oauth/authorize"
_token_url = PROTON_BASE_URL + "/oauth/token"

# need to set explicitly redirect_uri instead of leaving the lib to pre-fill redirect_uri
# when served behind nginx, the redirect_uri is localhost... and not the real url
_redirect_uri = URL + "/auth/proton/callback"

SESSION_ACTION_KEY = "oauth_action"
SESSION_STATE_KEY = "oauth_state"
DEFAULT_SCHEME = "auth.simplelogin"


def get_api_key_for_user(user: User) -> str:
    ak = ApiKey.create(
        user_id=user.id,
        name="Created via Login with Proton on mobile app",
        commit=True,
    )
    return ak.code


def extract_action() -> Optional[Action]:
    action = request.args.get("action")
    if action is not None:
        if action == "link":
            return Action.Link
        elif action == "login":
            return Action.Login
        else:
            LOG.w(f"Unknown action received: {action}")
            return None
    return Action.Login


def get_action_from_state() -> Action:
    oauth_action = session[SESSION_ACTION_KEY]
    if oauth_action == Action.Login.value:
        return Action.Login
    elif oauth_action == Action.Link.value:
        return Action.Link
    raise Exception(f"Unknown action in state: {oauth_action}")


@auth_bp.route("/proton/login")
def proton_login():
    if PROTON_CLIENT_ID is None or PROTON_CLIENT_SECRET is None:
        return redirect(url_for("auth.login"))

    action = extract_action()
    if action is None:
        return redirect(url_for("auth.login"))
    if action == Action.Link and not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    next_url = sanitize_next_url(request.args.get("next"))
    if next_url:
        session["oauth_next"] = next_url
    elif "oauth_next" in session:
        del session["oauth_next"]

    scheme = sanitize_scheme(request.args.get("scheme"))
    if scheme:
        session["oauth_scheme"] = scheme
    elif "oauth_scheme" in session:
        del session["oauth_scheme"]

    mode = request.args.get("mode", "session")
    if mode == "apikey":
        session["oauth_mode"] = "apikey"
    else:
        session["oauth_mode"] = "session"

    proton = OAuth2Session(PROTON_CLIENT_ID, redirect_uri=_redirect_uri)
    authorization_url, state = proton.authorization_url(_authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session[SESSION_STATE_KEY] = state
    session[SESSION_ACTION_KEY] = action.value
    return redirect(authorization_url)


@auth_bp.route("/proton/callback")
def proton_callback():
    if SESSION_STATE_KEY not in session or SESSION_STATE_KEY not in session:
        flash("Invalid state, please retry", "error")
        return redirect(url_for("auth.login"))
    if PROTON_CLIENT_ID is None or PROTON_CLIENT_SECRET is None:
        return redirect(url_for("auth.login"))

    # user clicks on cancel
    if "error" in request.args:
        flash("Please use another sign in method then", "warning")
        return redirect("/")

    proton = OAuth2Session(
        PROTON_CLIENT_ID,
        state=session[SESSION_STATE_KEY],
        redirect_uri=_redirect_uri,
    )

    def check_status_code(response: requests.Response) -> requests.Response:
        if response.status_code != 200:
            raise Exception(
                f"Bad Proton API response [status={response.status_code}]: {response.json()}"
            )
        return response

    proton.register_compliance_hook("access_token_response", check_status_code)

    headers = None
    if PROTON_EXTRA_HEADER_NAME and PROTON_EXTRA_HEADER_VALUE:
        headers = {PROTON_EXTRA_HEADER_NAME: PROTON_EXTRA_HEADER_VALUE}

    try:
        token = proton.fetch_token(
            _token_url,
            client_secret=PROTON_CLIENT_SECRET,
            authorization_response=request.url,
            verify=PROTON_VALIDATE_CERTS,
            method="GET",
            include_client_id=True,
            headers=headers,
        )
    except Exception as e:
        LOG.warning(f"Error fetching Proton token: {e}")
        flash("There was an error in the login process", "error")
        return redirect(url_for("auth.login"))

    credentials = convert_access_token(token["access_token"])
    action = get_action_from_state()

    proton_client = HttpProtonClient(
        PROTON_BASE_URL, credentials, get_remote_address(), verify=PROTON_VALIDATE_CERTS
    )
    handler = ProtonCallbackHandler(proton_client)
    proton_partner = get_proton_partner()

    next_url = session.get("oauth_next")
    if action == Action.Login:
        res = handler.handle_login(proton_partner)
    elif action == Action.Link:
        res = handler.handle_link(current_user, proton_partner)
    else:
        raise Exception(f"Unknown Action: {action.name}")

    if res.flash_message is not None:
        flash(res.flash_message, res.flash_category)

    oauth_scheme = session.get("oauth_scheme")
    if session.get("oauth_mode", "session") == "apikey":
        apikey = get_api_key_for_user(res.user)
        scheme = oauth_scheme or DEFAULT_SCHEME
        return redirect(f"{scheme}:///login?apikey={apikey}")

    if res.redirect_to_login:
        return redirect(url_for("auth.login"))

    if next_url and next_url[0] == "/" and oauth_scheme:
        next_url = f"{oauth_scheme}://{next_url}"

    redirect_url = next_url or res.redirect
    return after_login(res.user, redirect_url, login_from_proton=True)
