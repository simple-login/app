import random
from typing import Dict
from urllib.parse import urlparse

from flask import request, render_template, redirect
from flask_login import current_user

from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.jose_utils import make_id_token
from app.log import LOG
from app.models import (
    Client,
    AuthorizationCode,
    ClientUser,
    GenEmail,
    RedirectUri,
    OauthToken,
)
from app.oauth.base import oauth_bp
from app.oauth_models import get_response_types, ResponseType, Scope
from app.utils import random_string, encode_url, convert_to_id


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

    try:
        response_types: [ResponseType] = get_response_types(request)
    except ValueError:
        return (
            "response_type must be code, token, id_token or certain combination of these."
            " Please see /.well-known/openid-configuration to see what response_type are supported ",
            400,
        )

    if not redirect_uri:
        LOG.d("no redirect uri")
        return "redirect_uri must be set", 400

    client = Client.get_by(oauth_client_id=oauth_client_id)
    if not client:
        return f"no such client with oauth-client-id {oauth_client_id}", 400

    # check if redirect_uri is valid
    # allow localhost by default
    # todo: only allow https
    hostname, scheme = get_host_name_and_scheme(redirect_uri)
    if hostname != "localhost":
        if not RedirectUri.get_by(client_id=client.id, uri=redirect_uri):
            return f"{redirect_uri} is not authorized", 400

    # redirect from client website
    if request.method == "GET":
        if current_user.is_authenticated:
            suggested_email, other_emails, email_suffix = None, [], None

            # user has already allowed this client
            client_user: ClientUser = ClientUser.get_by(
                client_id=client.id, user_id=current_user.id
            )
            user_info = {}
            if client_user:
                LOG.debug("user %s has already allowed client %s", current_user, client)
                user_info = client_user.get_user_info()
            else:
                suggested_email, other_emails = current_user.suggested_emails()
                email_suffix = random_string(6)

            return render_template(
                "oauth/authorize.html",
                client=client,
                user_info=user_info,
                client_user=client_user,
                Scope=Scope,
                suggested_email=suggested_email,
                personal_email=current_user.email,
                other_emails=other_emails,
                email_suffix=email_suffix,
                EMAIL_DOMAIN=EMAIL_DOMAIN,
            )
        else:
            # after user logs in, redirect user back to this page
            return render_template(
                "oauth/authorize_nonlogin_user.html",
                client=client,
                next=request.url,
                Scope=Scope,
            )
    else:  # user allows or denies
        if request.form.get("button") == "deny":
            LOG.debug("User %s denies Client %s", current_user, client)
            final_redirect_uri = f"{redirect_uri}?error=deny&state={state}"
            return redirect(final_redirect_uri)

        LOG.debug("User %s allows Client %s", current_user, client)
        client_user = ClientUser.get_by(client_id=client.id, user_id=current_user.id)

        # user has already allowed this client, user cannot change information
        if client_user:
            LOG.d("user %s has already allowed client %s", current_user, client)
        else:
            email_suffix = request.form.get("email-suffix")
            custom_email_prefix = request.form.get("custom-email-prefix")
            chosen_email = request.form.get("suggested-email")

            gen_email = None
            if custom_email_prefix:
                # check if user can generate custom email
                if not current_user.can_create_custom_email():
                    raise Exception(f"User {current_user} cannot create custom email")

                email = f"{convert_to_id(custom_email_prefix)}.{email_suffix}@{EMAIL_DOMAIN}"
                LOG.d("create custom email alias %s for user %s", email, current_user)

                gen_email = GenEmail.create(
                    email=email, user_id=current_user.id, custom=True
                )
                db.session.flush()
            else:  # user picks an email from suggestion
                if chosen_email != current_user.email:
                    gen_email = GenEmail.get_by(email=chosen_email)
                    if not gen_email:
                        gen_email = GenEmail.create(
                            email=chosen_email, user_id=current_user.id
                        )
                        db.session.flush()

            client_user = ClientUser.create(
                client_id=client.id, user_id=current_user.id
            )
            if gen_email:
                client_user.gen_email_id = gen_email.id

            db.session.flush()
            LOG.d("create client-user for client %s, user %s", client, current_user)

        redirect_args = {}

        if state:
            redirect_args["state"] = state
        else:
            LOG.warning(
                "more security reason, state should be added. client %s", client
            )

        if scope:
            redirect_args["scope"] = scope

        for response_type in response_types:
            if response_type == ResponseType.CODE:
                # Create authorization code
                auth_code = AuthorizationCode.create(
                    client_id=client.id,
                    user_id=current_user.id,
                    code=random_string(),
                    scope=scope,
                    redirect_uri=redirect_uri,
                )
                db.session.add(auth_code)
                redirect_args["code"] = auth_code.code
            elif response_type == ResponseType.TOKEN:
                # create access-token
                oauth_token = OauthToken.create(
                    client_id=client.id,
                    user_id=current_user.id,
                    scope=scope,
                    redirect_uri=redirect_uri,
                    access_token=generate_access_token(),
                )
                db.session.add(oauth_token)
                redirect_args["access_token"] = oauth_token.access_token
            elif response_type == ResponseType.ID_TOKEN:
                redirect_args["id_token"] = make_id_token(client_user)

        db.session.commit()

        # construct redirect_uri with redirect_args
        return redirect(construct_url(redirect_uri, redirect_args))


def create_or_choose_gen_email(user) -> GenEmail:
    can_create_new_email = user.can_create_new_email()

    if can_create_new_email:
        gen_email = GenEmail.create_new_gen_email(user_id=user.id)
        db.session.flush()
        LOG.debug("generate email %s for user %s", gen_email.email, user)
    else:  # need to reuse one of the gen emails created
        LOG.d("pick a random email for gen emails for user %s", current_user)
        gen_emails = GenEmail.filter_by(user_id=current_user.id).all()
        gen_email = random.choice(gen_emails)

    return gen_email


def construct_url(url, args: Dict[str, str]):
    for i, (k, v) in enumerate(args.items()):
        # make sure to escape v
        v = encode_url(v)

        if i == 0:
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
    LOG.warning("access token already exists, generate a new one")
    return generate_access_token()


def get_host_name_and_scheme(url: str) -> (str, str):
    """http://localhost:7777?a=b -> (localhost, http) """
    url_comp = urlparse(url)

    return url_comp.hostname, url_comp.scheme
