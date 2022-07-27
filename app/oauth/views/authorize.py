from typing import Dict
from urllib.parse import urlparse

from flask import request, render_template, redirect, flash, url_for
from flask_login import current_user

from app.alias_suffix import get_alias_suffixes, check_suffix_signature
from app.alias_utils import check_alias_prefix
from app.config import EMAIL_DOMAIN
from app.db import Session
from app.jose_utils import make_id_token
from app.log import LOG
from app.models import (
    Client,
    AuthorizationCode,
    ClientUser,
    Alias,
    RedirectUri,
    OauthToken,
    DeletedAlias,
    DomainDeletedAlias,
)
from app.oauth.base import oauth_bp
from app.oauth_models import (
    get_response_types,
    ResponseType,
    Scope,
    SUPPORTED_OPENID_FLOWS,
    SUPPORTED_OPENID_FLOWS_STR,
    response_types_to_str,
)
from app.utils import random_string, encode_url


@oauth_bp.route("/authorize", methods=["GET", "POST"])
def authorize():
    """
    Redirected from client when user clicks on "Login with Server".
    This is a GET request with the following field in url
    - client_id
    - (optional) state
    - response_type: must be code
    """
    oauth_client_id = request.args.get("client_id")
    state = request.args.get("state")
    scope = request.args.get("scope")
    redirect_uri = request.args.get("redirect_uri")
    response_mode = request.args.get("response_mode")
    nonce = request.args.get("nonce")

    try:
        response_types: [ResponseType] = get_response_types(request)
    except ValueError:
        return (
            "response_type must be code, token, id_token or certain combination of these."
            " Please see /.well-known/openid-configuration to see what response_type are supported ",
            400,
        )

    if set(response_types) not in SUPPORTED_OPENID_FLOWS:
        return (
            f"SimpleLogin only support the following OIDC flows: {SUPPORTED_OPENID_FLOWS_STR}",
            400,
        )

    if not redirect_uri:
        LOG.d("no redirect uri")
        return "redirect_uri must be set", 400

    client = Client.get_by(oauth_client_id=oauth_client_id)
    if not client:
        return redirect(url_for("auth.login"))

    # allow localhost by default
    # allow any redirect_uri if the app isn't approved
    hostname, scheme = get_host_name_and_scheme(redirect_uri)
    if hostname != "localhost" and hostname != "127.0.0.1":
        # support custom scheme for mobile app
        if scheme == "http":
            flash("The external client must use HTTPS", "error")
            return redirect(url_for("dashboard.index"))

        # check if redirect_uri is valid
        if not RedirectUri.get_by(client_id=client.id, uri=redirect_uri):
            flash("The external client is using an invalid URL", "error")
            return redirect(url_for("dashboard.index"))

    # redirect from client website
    if request.method == "GET":
        if current_user.is_authenticated:
            suggested_email, other_emails, email_suffix = None, [], None
            suggested_name, other_names = None, []

            # user has already allowed this client
            client_user: ClientUser = ClientUser.get_by(
                client_id=client.id, user_id=current_user.id
            )
            user_info = {}
            if client_user:
                LOG.d("user %s has already allowed client %s", current_user, client)
                user_info = client_user.get_user_info()

                # redirect user to the client page
                redirect_args = construct_redirect_args(
                    client,
                    client_user,
                    nonce,
                    redirect_uri,
                    response_types,
                    scope,
                    state,
                )
                fragment = get_fragment(response_mode, response_types)

                # construct redirect_uri with redirect_args
                return redirect(construct_url(redirect_uri, redirect_args, fragment))
            else:
                suggested_email, other_emails = current_user.suggested_emails(
                    client.name
                )
                suggested_name, other_names = current_user.suggested_names()

                user_custom_domains = [
                    cd.domain for cd in current_user.verified_custom_domains()
                ]
                suffixes = get_alias_suffixes(current_user)

            return render_template(
                "oauth/authorize.html",
                Scope=Scope,
                EMAIL_DOMAIN=EMAIL_DOMAIN,
                **locals(),
            )
        else:
            # after user logs in, redirect user back to this page
            return render_template(
                "oauth/authorize_nonlogin_user.html",
                client=client,
                next=request.url,
                Scope=Scope,
            )
    else:  # POST - user allows or denies
        if not current_user.is_authenticated or not current_user.is_active:
            LOG.i(
                "Attempt to validate a OAUth allow request by an unauthenticated user"
            )
            return redirect(url_for("auth.login", next=request.url))

        if request.form.get("button") == "deny":
            LOG.d("User %s denies Client %s", current_user, client)
            final_redirect_uri = f"{redirect_uri}?error=deny&state={state}"
            return redirect(final_redirect_uri)

        LOG.d("User %s allows Client %s", current_user, client)
        client_user = ClientUser.get_by(client_id=client.id, user_id=current_user.id)

        # user has already allowed this client, user cannot change information
        if client_user:
            LOG.d("user %s has already allowed client %s", current_user, client)
        else:
            alias_prefix = request.form.get("prefix")
            signed_suffix = request.form.get("suffix")

            alias = None

            # user creates a new alias, not using suggested alias
            if alias_prefix:
                # should never happen as this is checked on the front-end
                if not current_user.can_create_new_alias():
                    raise Exception(f"User {current_user} cannot create custom email")

                alias_prefix = alias_prefix.strip().lower().replace(" ", "")

                if not check_alias_prefix(alias_prefix):
                    flash(
                        "Only lowercase letters, numbers, dashes (-), dots (.) and underscores (_) "
                        "are currently supported for alias prefix. Cannot be more than 40 letters",
                        "error",
                    )
                    return redirect(request.url)

                # hypothesis: user will click on the button in the 600 secs
                try:
                    alias_suffix = check_suffix_signature(signed_suffix)
                    if not alias_suffix:
                        LOG.w("Alias creation time expired for %s", current_user)
                        flash("Alias creation time is expired, please retry", "warning")
                        return redirect(request.url)
                except Exception:
                    LOG.w("Alias suffix is tampered, user %s", current_user)
                    flash("Unknown error, refresh the page", "error")
                    return redirect(request.url)

                user_custom_domains = [
                    cd.domain for cd in current_user.verified_custom_domains()
                ]

                from app.alias_suffix import verify_prefix_suffix

                if verify_prefix_suffix(current_user, alias_prefix, alias_suffix):
                    full_alias = alias_prefix + alias_suffix

                    if (
                        Alias.get_by(email=full_alias)
                        or DeletedAlias.get_by(email=full_alias)
                        or DomainDeletedAlias.get_by(email=full_alias)
                    ):
                        LOG.e("alias %s already used, very rare!", full_alias)
                        flash(f"Alias {full_alias} already used", "error")
                        return redirect(request.url)
                    else:
                        alias = Alias.create(
                            user_id=current_user.id,
                            email=full_alias,
                            mailbox_id=current_user.default_mailbox_id,
                        )

                        Session.flush()
                        flash(f"Alias {full_alias} has been created", "success")
                # only happen if the request has been "hacked"
                else:
                    flash("something went wrong", "warning")
                    return redirect(request.url)
            # User chooses one of the suggestions
            else:
                chosen_email = request.form.get("suggested-email")
                # todo: add some checks on chosen_email
                if chosen_email != current_user.email:
                    alias = Alias.get_by(email=chosen_email)
                    if not alias:
                        alias = Alias.create(
                            email=chosen_email,
                            user_id=current_user.id,
                            mailbox_id=current_user.default_mailbox_id,
                        )
                        Session.flush()

            suggested_name = request.form.get("suggested-name")
            custom_name = request.form.get("custom-name")

            use_default_avatar = request.form.get("avatar-choice") == "default"

            client_user = ClientUser.create(
                client_id=client.id, user_id=current_user.id
            )
            if alias:
                client_user.alias_id = alias.id

            if custom_name:
                client_user.name = custom_name
            elif suggested_name != current_user.name:
                client_user.name = suggested_name

            if use_default_avatar:
                # use default avatar
                LOG.d("use default avatar for user %s client %s", current_user, client)
                client_user.default_avatar = True

            Session.flush()
            LOG.d("create client-user for client %s, user %s", client, current_user)

        redirect_args = construct_redirect_args(
            client, client_user, nonce, redirect_uri, response_types, scope, state
        )
        fragment = get_fragment(response_mode, response_types)

        # construct redirect_uri with redirect_args
        return redirect(construct_url(redirect_uri, redirect_args, fragment))


def get_fragment(response_mode, response_types):
    # should all params appended the url using fragment (#) or query
    fragment = False
    if response_mode and response_mode == "fragment":
        fragment = True
    # if response_types contain "token" => implicit flow => should use fragment
    # except if client sets explicitly response_mode
    if not response_mode:
        if ResponseType.TOKEN in response_types:
            fragment = True
    return fragment


def construct_redirect_args(
    client, client_user, nonce, redirect_uri, response_types, scope, state
) -> dict:
    redirect_args = {}
    if state:
        redirect_args["state"] = state
    else:
        LOG.w("more security reason, state should be added. client %s", client)
    if scope:
        redirect_args["scope"] = scope

    auth_code = None
    if ResponseType.CODE in response_types:
        auth_code = AuthorizationCode.create(
            client_id=client.id,
            user_id=current_user.id,
            code=random_string(),
            scope=scope,
            redirect_uri=redirect_uri,
            response_type=response_types_to_str(response_types),
            nonce=nonce,
        )
        redirect_args["code"] = auth_code.code

    oauth_token = None
    if ResponseType.TOKEN in response_types:
        # create access-token
        oauth_token = OauthToken.create(
            client_id=client.id,
            user_id=current_user.id,
            scope=scope,
            redirect_uri=redirect_uri,
            access_token=generate_access_token(),
            response_type=response_types_to_str(response_types),
        )
        Session.add(oauth_token)
        redirect_args["access_token"] = oauth_token.access_token
    if ResponseType.ID_TOKEN in response_types:
        redirect_args["id_token"] = make_id_token(
            client_user,
            nonce,
            oauth_token.access_token if oauth_token else None,
            auth_code.code if auth_code else None,
        )
    Session.commit()
    return redirect_args


def construct_url(url, args: Dict[str, str], fragment: bool = False):
    for i, (k, v) in enumerate(args.items()):
        # make sure to escape v
        v = encode_url(v)

        if i == 0:
            if fragment:
                url += f"#{k}={v}"
            else:
                url += f"?{k}={v}"
        else:
            url += f"&{k}={v}"

    return url


def generate_access_token() -> str:
    """generate an access-token that does not exist before"""
    access_token = random_string(40)

    if not OauthToken.get_by(access_token=access_token):
        return access_token

    # Rerun the function
    LOG.w("access token already exists, generate a new one")
    return generate_access_token()


def get_host_name_and_scheme(url: str) -> (str, str):
    """http://localhost:7777?a=b -> (localhost, http)"""
    url_comp = urlparse(url)

    return url_comp.hostname, url_comp.scheme
