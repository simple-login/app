import secrets
import string

import facebook
import google.oauth2.credentials
import googleapiclient.discovery
from flask import jsonify, request
from flask_login import login_user
from itsdangerous import Signer

from app import email_utils
from app.api.base import api_bp
from app.config import FLASK_SECRET, DISABLE_REGISTRATION
from app.dashboard.views.setting import send_reset_password_email
from app.db import Session
from app.email_utils import (
    email_can_be_used_as_mailbox,
    personal_email_already_used,
    send_email,
    render,
)
from app.events.auth_event import LoginEvent, RegisterEvent
from app.extensions import limiter
from app.log import LOG
from app.models import User, ApiKey, SocialAuth, AccountActivation
from app.utils import sanitize_email


@api_bp.route("/auth/login", methods=["POST"])
@limiter.limit("10/minute")
def auth_login():
    """
    Authenticate user
    Input:
        email
        password
        device: to create an ApiKey associated with this device
    Output:
        200 and user info containing:
        {
            name: "John Wick",
            mfa_enabled: true,
            mfa_key: "a long string",
            api_key: "a long string"
        }

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    email = sanitize_email(data.get("email"))
    password = data.get("password")
    device = data.get("device")

    user = User.filter_by(email=email).first()

    if not user or not user.check_password(password):
        LoginEvent(LoginEvent.ActionType.failed, LoginEvent.Source.api).send()
        return jsonify(error="Email or password incorrect"), 400
    elif user.disabled:
        LoginEvent(LoginEvent.ActionType.disabled_login, LoginEvent.Source.api).send()
        return jsonify(error="Account disabled"), 400
    elif not user.activated:
        LoginEvent(LoginEvent.ActionType.not_activated, LoginEvent.Source.api).send()
        return jsonify(error="Account not activated"), 422
    elif user.fido_enabled():
        # allow user who has TOTP enabled to continue using the mobile app
        if not user.enable_otp:
            return jsonify(error="Currently we don't support FIDO on mobile yet"), 403

    LoginEvent(LoginEvent.ActionType.success, LoginEvent.Source.api).send()
    return jsonify(**auth_payload(user, device)), 200


@api_bp.route("/auth/register", methods=["POST"])
@limiter.limit("10/minute")
def auth_register():
    """
    User signs up - will need to activate their account with an activation code.
    Input:
        email
        password
    Output:
        200: user needs to confirm their account

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    email = sanitize_email(data.get("email"))
    password = data.get("password")

    if DISABLE_REGISTRATION:
        RegisterEvent(RegisterEvent.ActionType.failed, RegisterEvent.Source.api).send()
        return jsonify(error="registration is closed"), 400
    if not email_can_be_used_as_mailbox(email) or personal_email_already_used(email):
        RegisterEvent(
            RegisterEvent.ActionType.invalid_email, RegisterEvent.Source.api
        ).send()
        return jsonify(error=f"cannot use {email} as personal inbox"), 400

    if not password or len(password) < 8:
        RegisterEvent(RegisterEvent.ActionType.failed, RegisterEvent.Source.api).send()
        return jsonify(error="password too short"), 400

    if len(password) > 100:
        RegisterEvent(RegisterEvent.ActionType.failed, RegisterEvent.Source.api).send()
        return jsonify(error="password too long"), 400

    LOG.d("create user %s", email)
    user = User.create(email=email, name="", password=password)
    Session.flush()

    # create activation code
    code = "".join([str(secrets.choice(string.digits)) for _ in range(6)])
    AccountActivation.create(user_id=user.id, code=code)
    Session.commit()

    send_email(
        email,
        "Just one more step to join SimpleLogin",
        render("transactional/code-activation.txt.jinja2", code=code),
        render("transactional/code-activation.html", code=code),
    )

    RegisterEvent(RegisterEvent.ActionType.success, RegisterEvent.Source.api).send()
    return jsonify(msg="User needs to confirm their account"), 200


@api_bp.route("/auth/activate", methods=["POST"])
@limiter.limit("10/minute")
def auth_activate():
    """
    User enters the activation code to confirm their account.
    Input:
        email
        code
    Output:
        200: user account is now activated, user can login now
        400: wrong email, code
        410: wrong code too many times

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    email = sanitize_email(data.get("email"))
    code = data.get("code")

    user = User.get_by(email=email)

    # do not use a different message to avoid exposing existing email
    if not user or user.activated:
        return jsonify(error="Wrong email or code"), 400

    account_activation = AccountActivation.get_by(user_id=user.id)
    if not account_activation:
        return jsonify(error="Wrong email or code"), 400

    if account_activation.code != code:
        # decrement nb tries
        account_activation.tries -= 1
        Session.commit()

        if account_activation.tries == 0:
            AccountActivation.delete(account_activation.id)
            Session.commit()
            return jsonify(error="Too many wrong tries"), 410

        return jsonify(error="Wrong email or code"), 400

    LOG.d("activate user %s", user)
    user.activated = True
    AccountActivation.delete(account_activation.id)
    Session.commit()

    return jsonify(msg="Account is activated, user can login now"), 200


@api_bp.route("/auth/reactivate", methods=["POST"])
@limiter.limit("10/minute")
def auth_reactivate():
    """
    User asks for another activation code
    Input:
        email
    Output:
        200: user is going to receive an email for activate their account

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    email = sanitize_email(data.get("email"))
    user = User.get_by(email=email)

    # do not use a different message to avoid exposing existing email
    if not user or user.activated:
        return jsonify(error="Something went wrong"), 400

    account_activation = AccountActivation.get_by(user_id=user.id)
    if account_activation:
        AccountActivation.delete(account_activation.id)
        Session.commit()

    # create activation code
    code = "".join([str(secrets.choice(string.digits)) for _ in range(6)])
    AccountActivation.create(user_id=user.id, code=code)
    Session.commit()

    send_email(
        email,
        "Just one more step to join SimpleLogin",
        render("transactional/code-activation.txt.jinja2", code=code),
        render("transactional/code-activation.html", code=code),
    )

    return jsonify(msg="User needs to confirm their account"), 200


@api_bp.route("/auth/facebook", methods=["POST"])
@limiter.limit("10/minute")
def auth_facebook():
    """
    Authenticate user with Facebook
    Input:
        facebook_token: facebook access token
        device: to create an ApiKey associated with this device
    Output:
        200 and user info containing:
        {
            name: "John Wick",
            mfa_enabled: true,
            mfa_key: "a long string",
            api_key: "a long string"
        }

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    facebook_token = data.get("facebook_token")
    device = data.get("device")

    graph = facebook.GraphAPI(access_token=facebook_token)
    user_info = graph.get_object("me", fields="email,name")
    email = sanitize_email(user_info.get("email"))

    user = User.get_by(email=email)

    if not user:
        if DISABLE_REGISTRATION:
            return jsonify(error="registration is closed"), 400
        if not email_can_be_used_as_mailbox(email) or personal_email_already_used(
            email
        ):
            return jsonify(error=f"cannot use {email} as personal inbox"), 400

        LOG.d("create facebook user with %s", user_info)
        user = User.create(email=email, name=user_info["name"], activated=True)
        Session.commit()
        email_utils.send_welcome_email(user)

    if not SocialAuth.get_by(user_id=user.id, social="facebook"):
        SocialAuth.create(user_id=user.id, social="facebook")
        Session.commit()

    return jsonify(**auth_payload(user, device)), 200


@api_bp.route("/auth/google", methods=["POST"])
@limiter.limit("10/minute")
def auth_google():
    """
    Authenticate user with Google
    Input:
        google_token: Google access token
        device: to create an ApiKey associated with this device
    Output:
        200 and user info containing:
        {
            name: "John Wick",
            mfa_enabled: true,
            mfa_key: "a long string",
            api_key: "a long string"
        }

    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    google_token = data.get("google_token")
    device = data.get("device")

    cred = google.oauth2.credentials.Credentials(token=google_token)

    build = googleapiclient.discovery.build("oauth2", "v2", credentials=cred)

    user_info = build.userinfo().get().execute()
    email = sanitize_email(user_info.get("email"))

    user = User.get_by(email=email)

    if not user:
        if DISABLE_REGISTRATION:
            return jsonify(error="registration is closed"), 400
        if not email_can_be_used_as_mailbox(email) or personal_email_already_used(
            email
        ):
            return jsonify(error=f"cannot use {email} as personal inbox"), 400

        LOG.d("create Google user with %s", user_info)
        user = User.create(email=email, name="", activated=True)
        Session.commit()
        email_utils.send_welcome_email(user)

    if not SocialAuth.get_by(user_id=user.id, social="google"):
        SocialAuth.create(user_id=user.id, social="google")
        Session.commit()

    return jsonify(**auth_payload(user, device)), 200


def auth_payload(user, device) -> dict:
    ret = {"name": user.name or "", "email": user.email, "mfa_enabled": user.enable_otp}

    # do not give api_key, user can only obtain api_key after OTP verification
    if user.enable_otp:
        s = Signer(FLASK_SECRET)
        ret["mfa_key"] = s.sign(str(user.id))
        ret["api_key"] = None
    else:
        api_key = ApiKey.get_by(user_id=user.id, name=device)
        if not api_key:
            LOG.d("create new api key for %s and %s", user, device)
            api_key = ApiKey.create(user.id, device)
            Session.commit()
        ret["mfa_key"] = None
        ret["api_key"] = api_key.code

        # so user is automatically logged in on the web
        login_user(user)

    return ret


@api_bp.route("/auth/forgot_password", methods=["POST"])
@limiter.limit("10/minute")
def forgot_password():
    """
    User forgot password
    Input:
        email
    Output:
        200 and a reset password email is sent to user
        400 if email not exist

    """
    data = request.get_json()
    if not data or not data.get("email"):
        return jsonify(error="request body must contain email"), 400

    email = sanitize_email(data.get("email"))

    user = User.get_by(email=email)

    if user:
        send_reset_password_email(user)

    return jsonify(ok=True)
