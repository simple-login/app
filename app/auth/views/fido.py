import json
import secrets
import webauthn
from app.config import RP_ID

from flask import request, render_template, redirect, url_for, flash, session
from flask_login import login_user
from flask_wtf import FlaskForm
from wtforms import HiddenField, validators

from app.auth.base import auth_bp
from app.config import MFA_USER_ID
from app.log import LOG
from app.models import User
from app.extensions import db


class FidoTokenForm(FlaskForm):
    sk_assertion = HiddenField("sk_assertion", validators=[validators.DataRequired()])


@auth_bp.route("/fido", methods=["GET", "POST"])
def fido():
    # passed from login page
    user_id = session.get(MFA_USER_ID)

    # user access this page directly without passing by login page
    if not user_id:
        flash("Unknown error, redirect back to main page", "warning")
        return redirect(url_for("auth.login"))

    user = User.get(user_id)

    if not (user and (user.fido_enabled())):
        flash("Only user with security key linked should go to this page", "warning")
        return redirect(url_for("auth.login"))

    fido_token_form = FidoTokenForm()

    next_url = request.args.get("next")

    webauthn_user = webauthn.WebAuthnUser(
        user.fido_uuid,
        user.email,
        user.name,
        False,
        user.fido_credential_id,
        user.fido_pk,
        user.fido_sign_count,
        RP_ID,
    )

    # Handling POST requests
    if fido_token_form.validate_on_submit():
        try:
            sk_assertion = json.loads(fido_token_form.sk_assertion.data)
        except Exception as e:
            flash("Key verification failed. Error: Invalid Payload", "warning")
            return redirect(url_for("auth.login"))

        challenge = session["fido_challenge"]
        credential_id = sk_assertion["id"]

        webauthn_assertion_response = webauthn.WebAuthnAssertionResponse(
            webauthn_user, sk_assertion, challenge, SITE_URL, uv_required=False
        )

        is_webauthn_verified = False
        try:
            new_sign_count = webauthn_assertion_response.verify()
            is_webauthn_verified = True
        except Exception as e:
            LOG.error(f"An error occurred in WebAuthn verification process: {e}")
            flash("Key verification failed.", "warning")

        if is_webauthn_verified:
            user.fido_sign_count = new_sign_count
            db.session.commit()
            del session[MFA_USER_ID]

            login_user(user)
            flash(f"Welcome back {user.name}!", "success")

            # User comes to login page from another page
            if next_url:
                LOG.debug("redirect user to %s", next_url)
                return redirect(next_url)
            else:
                LOG.debug("redirect user to dashboard")
                return redirect(url_for("dashboard.index"))
        else:
            # Verification failed, put else here to make structure clear
            pass

    # Prepare information for key registration process
    session.pop("challenge", None)
    challenge = secrets.token_urlsafe(32)

    session["fido_challenge"] = challenge.rstrip("=")

    webauthn_assertion_options = webauthn.WebAuthnAssertionOptions(
        webauthn_user, challenge
    )
    webauthn_assertion_options = webauthn_assertion_options.assertion_dict

    return render_template(
        "auth/fido.html",
        fido_token_form=fido_token_form,
        webauthn_assertion_options=webauthn_assertion_options,
        enable_otp=user.enable_otp,
    )
