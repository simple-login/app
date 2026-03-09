import json
import secrets

import webauthn
from flask import render_template, flash, redirect, url_for, session, request
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from time import time
from wtforms import HiddenField, validators

from app.config import ADMIN_FIDO_REQUIRED, RP_ID, URL
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import Fido
from app.utils import sanitize_next_url

_ADMIN_GAP = 900


class FidoTokenForm(FlaskForm):
    sk_assertion = HiddenField("sk_assertion", validators=[validators.DataRequired()])


@dashboard_bp.route("/enter_admin", methods=["GET", "POST"])
@limiter.limit("10/minute")
@login_required
def enter_admin():
    if ADMIN_FIDO_REQUIRED == "none":
        next_url = sanitize_next_url(request.args.get("next"))
        return redirect(next_url or url_for("dashboard.index"))

    if not current_user.fido_enabled():
        flash(
            "A security key is required for admin access but none is configured on your account.",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    fido_token_form = FidoTokenForm()
    next_url = sanitize_next_url(request.args.get("next"))

    if fido_token_form.validate_on_submit():
        try:
            sk_assertion = json.loads(fido_token_form.sk_assertion.data)
        except Exception:
            flash("Key verification failed. Error: Invalid Payload", "warning")
            return redirect(
                url_for("dashboard.enter_admin", next=request.args.get("next"))
            )

        challenge = session.get("admin_fido_challenge")
        if not challenge:
            flash("Session expired. Please try again.", "warning")
            return redirect(
                url_for("dashboard.enter_admin", next=request.args.get("next"))
            )

        authenticator_attachment = sk_assertion.get("authenticatorAttachment")
        if (
            ADMIN_FIDO_REQUIRED == "hardware"
            and authenticator_attachment != "cross-platform"
        ):
            LOG.w(
                "Admin FIDO hardware check failed: authenticatorAttachment=%s",
                authenticator_attachment,
            )
            flash(
                "Only hardware security keys (e.g. YubiKey) are accepted for admin access.",
                "warning",
            )
            return redirect(
                url_for("dashboard.enter_admin", next=request.args.get("next"))
            )

        try:
            fido_key = Fido.get_by(
                uuid=current_user.fido_uuid, credential_id=sk_assertion["id"]
            )
            if not fido_key:
                raise Exception("Unknown credential")

            webauthn_user = webauthn.WebAuthnUser(
                current_user.fido_uuid,
                current_user.email,
                current_user.name if current_user.name else current_user.email,
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
            LOG.w("Admin FIDO verification failed: %s", e)
            flash("Key verification failed.", "warning")
            return redirect(
                url_for("dashboard.enter_admin", next=request.args.get("next"))
            )

        fido_key.sign_count = new_sign_count
        Session.commit()

        session["admin_time"] = int(time())
        session["admin_hardware_auth"] = authenticator_attachment == "cross-platform"

        LOG.d("Admin FIDO auth success for user %s", current_user.id)

        if next_url:
            return redirect(next_url)
        return redirect(url_for("dashboard.index"))

    # Prepare FIDO challenge
    session.pop("admin_fido_challenge", None)
    challenge = secrets.token_urlsafe(32)
    session["admin_fido_challenge"] = challenge.rstrip("=")

    fidos = Fido.filter_by(uuid=current_user.fido_uuid).all()
    webauthn_users = [
        webauthn.WebAuthnUser(
            current_user.fido_uuid,
            current_user.email,
            current_user.name if current_user.name else current_user.email,
            False,
            fido.credential_id,
            fido.public_key,
            fido.sign_count,
            RP_ID,
        )
        for fido in fidos
    ]

    webauthn_assertion_options = webauthn.WebAuthnAssertionOptions(
        webauthn_users, challenge
    ).assertion_dict
    try:
        for credential in webauthn_assertion_options["allowCredentials"]:
            del credential["transports"]
    except KeyError:
        pass

    return render_template(
        "dashboard/enter_admin.html",
        fido_token_form=fido_token_form,
        webauthn_assertion_options=webauthn_assertion_options,
        next_url=next_url,
        hardware_required=ADMIN_FIDO_REQUIRED == "hardware",
    )
