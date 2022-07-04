import json
import secrets
from time import time

import webauthn
from flask import (
    request,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    make_response,
    g,
)
from flask_login import login_user
from flask_wtf import FlaskForm
from wtforms import HiddenField, validators, BooleanField

from app.auth.base import auth_bp
from app.config import MFA_USER_ID
from app.config import RP_ID, URL
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import User, Fido, MfaBrowser
from app.utils import sanitize_next_url


class FidoTokenForm(FlaskForm):
    sk_assertion = HiddenField("sk_assertion", validators=[validators.DataRequired()])
    remember = BooleanField(
        "attr", default=False, description="Remember this browser for 30 days"
    )


@auth_bp.route("/fido", methods=["GET", "POST"])
@limiter.limit(
    "10/minute", deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit
)
def fido():
    # passed from login page
    user_id = session.get(MFA_USER_ID)

    # user access this page directly without passing by login page
    if not user_id:
        flash("Unknown error, redirect back to main page", "warning")
        return redirect(url_for("auth.login"))

    user = User.get(user_id)

    if not (user and user.fido_enabled()):
        flash("Only user with security key linked should go to this page", "warning")
        return redirect(url_for("auth.login"))

    auto_activate = True
    fido_token_form = FidoTokenForm()

    next_url = sanitize_next_url(request.args.get("next"))

    if request.cookies.get("mfa"):
        browser = MfaBrowser.get_by(token=request.cookies.get("mfa"))
        if browser and not browser.is_expired() and browser.user_id == user.id:
            login_user(user)
            flash(f"Welcome back!", "success")
            # Redirect user to correct page
            return redirect(next_url or url_for("dashboard.index"))
        else:
            # Trigger rate limiter
            g.deduct_limit = True

    # Handling POST requests
    if fido_token_form.validate_on_submit():
        try:
            sk_assertion = json.loads(fido_token_form.sk_assertion.data)
        except Exception:
            flash("Key verification failed. Error: Invalid Payload", "warning")
            return redirect(url_for("auth.login"))

        challenge = session["fido_challenge"]

        try:
            fido_key = Fido.get_by(
                uuid=user.fido_uuid, credential_id=sk_assertion["id"]
            )
            webauthn_user = webauthn.WebAuthnUser(
                user.fido_uuid,
                user.email,
                user.name if user.name else user.email,
                False,
                fido_key.credential_id,
                fido_key.public_key,
                fido_key.sign_count,
                RP_ID,
            )
            webauthn_assertion_response = webauthn.WebAuthnAssertionResponse(
                webauthn_user, sk_assertion, challenge, URL, uv_required=False
            )
            new_sign_count = webauthn_assertion_response.verify()
        except Exception as e:
            LOG.w(f"An error occurred in WebAuthn verification process: {e}")
            flash("Key verification failed.", "warning")
            # Trigger rate limiter
            g.deduct_limit = True
            auto_activate = False
        else:
            user.fido_sign_count = new_sign_count
            Session.commit()
            del session[MFA_USER_ID]

            session["sudo_time"] = int(time())
            login_user(user)
            flash(f"Welcome back!", "success")

            # Redirect user to correct page
            response = make_response(redirect(next_url or url_for("dashboard.index")))

            if fido_token_form.remember.data:
                browser = MfaBrowser.create_new(user=user)
                Session.commit()
                response.set_cookie(
                    "mfa",
                    value=browser.token,
                    expires=browser.expires.datetime,
                    secure=True if URL.startswith("https") else False,
                    httponly=True,
                    samesite="Lax",
                )

            return response

    # Prepare information for key registration process
    session.pop("challenge", None)
    challenge = secrets.token_urlsafe(32)

    session["fido_challenge"] = challenge.rstrip("=")

    fidos = Fido.filter_by(uuid=user.fido_uuid).all()
    webauthn_users = []
    for fido in fidos:
        webauthn_users.append(
            webauthn.WebAuthnUser(
                user.fido_uuid,
                user.email,
                user.name if user.name else user.email,
                False,
                fido.credential_id,
                fido.public_key,
                fido.sign_count,
                RP_ID,
            )
        )

    webauthn_assertion_options = webauthn.WebAuthnAssertionOptions(
        webauthn_users, challenge
    )
    webauthn_assertion_options = webauthn_assertion_options.assertion_dict
    try:
        # HACK: We need to upgrade to webauthn > 1 so it can support specifying the transports
        for credential in webauthn_assertion_options["allowCredentials"]:
            del credential["transports"]
    except KeyError:
        # Should never happen but...
        pass

    return render_template(
        "auth/fido.html",
        fido_token_form=fido_token_form,
        webauthn_assertion_options=webauthn_assertion_options,
        enable_otp=user.enable_otp,
        auto_activate=auto_activate,
        next_url=next_url,
    )
