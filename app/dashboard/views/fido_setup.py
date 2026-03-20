import json
import secrets
import struct
import uuid

import cbor2
import webauthn
from flask import render_template, flash, redirect, url_for, session
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, HiddenField, validators

from app.config import RP_ID, URL
from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.log import LOG
from app.models import Fido, RecoveryCode
from app.user_settings import regenerate_user_alternative_id


def extract_aaguid(att_obj_b64: str) -> str | None:
    """Extract the AAGUID from the attestation object's authData (bytes 37-53)."""
    try:
        # webauthn.py uses _webauthn_b64_decode which handles urlsafe base64
        padding = 4 - len(att_obj_b64) % 4
        if padding != 4:
            att_obj_b64 += "=" * padding
        import base64

        raw = base64.urlsafe_b64decode(att_obj_b64)
        att_obj = cbor2.loads(raw)
        auth_data = att_obj.get("authData", b"")
        if len(auth_data) < 53:
            return None
        flags = struct.unpack("!B", auth_data[32:33])[0]
        # AT flag (bit 6) indicates attested credential data is present
        if not (flags & 0x40):
            return None
        aaguid_bytes = auth_data[37:53]
        return str(uuid.UUID(bytes=aaguid_bytes))
    except Exception as e:
        LOG.w(f"Failed to extract AAGUID: {e}")
        return None


class FidoTokenForm(FlaskForm):
    key_name = StringField("key_name", validators=[validators.DataRequired()])
    sk_assertion = HiddenField("sk_assertion", validators=[validators.DataRequired()])


@dashboard_bp.route("/fido_setup", methods=["GET", "POST"])
@login_required
@sudo_required
def fido_setup():
    if current_user.fido_uuid is not None:
        fidos = Fido.filter_by(uuid=current_user.fido_uuid).all()
    else:
        fidos = []

    fido_token_form = FidoTokenForm()

    # Handling POST requests
    if fido_token_form.validate_on_submit():
        try:
            sk_assertion = json.loads(fido_token_form.sk_assertion.data)
        except Exception:
            flash("Key registration failed. Error: Invalid Payload", "warning")
            return redirect(url_for("dashboard.index"))

        fido_uuid = session["fido_uuid"]
        challenge = session["fido_challenge"]

        fido_reg_response = webauthn.WebAuthnRegistrationResponse(
            RP_ID,
            URL,
            sk_assertion,
            challenge,
            trusted_attestation_cert_required=False,
            none_attestation_permitted=True,
        )

        try:
            fido_credential = fido_reg_response.verify()
        except Exception as e:
            LOG.w(f"An error occurred in WebAuthn registration process: {e}")
            flash("Key registration failed.", "warning")
            return redirect(url_for("dashboard.index"))

        if current_user.fido_uuid is None:
            current_user.fido_uuid = fido_uuid
            Session.flush()

        transports = sk_assertion.get("transports")
        Fido.create(
            credential_id=str(fido_credential.credential_id, "utf-8"),
            uuid=fido_uuid,
            public_key=str(fido_credential.public_key, "utf-8"),
            sign_count=fido_credential.sign_count,
            name=fido_token_form.key_name.data,
            user_id=current_user.id,
            credential_type=sk_assertion.get("type"),
            authenticator_attachment=sk_assertion.get("authenticatorAttachment"),
            transports=transports if isinstance(transports, list) else None,
            aaguid=extract_aaguid(sk_assertion.get("attObj", "")),
        )
        regenerate_user_alternative_id(current_user)
        Session.commit()

        LOG.d(
            f"credential_id={str(fido_credential.credential_id, 'utf-8')} added for {fido_uuid}"
        )

        flash("Security key has been activated", "success")
        recovery_codes = RecoveryCode.generate(current_user)
        return render_template(
            "dashboard/recovery_code.html", recovery_codes=recovery_codes
        )

    # Prepare information for key registration process
    fido_uuid = (
        str(uuid.uuid4()) if current_user.fido_uuid is None else current_user.fido_uuid
    )
    challenge = secrets.token_urlsafe(32)

    credential_create_options = webauthn.WebAuthnMakeCredentialOptions(
        challenge,
        "SimpleLogin",
        RP_ID,
        fido_uuid,
        current_user.email,
        current_user.name if current_user.name else current_user.email,
        False,
        attestation="none",
        user_verification="discouraged",
    )

    # Don't think this one should be used, but it's not configurable by arguments
    # https://www.w3.org/TR/webauthn/#sctn-location-extension
    registration_dict = credential_create_options.registration_dict
    del registration_dict["extensions"]["webauthn.loc"]

    # Prevent user from adding duplicated keys
    for fido in fidos:
        registration_dict["excludeCredentials"].append(
            {
                "type": "public-key",
                "id": fido.credential_id,
                "transports": ["usb", "nfc", "ble", "internal"],
            }
        )

    session["fido_uuid"] = fido_uuid
    session["fido_challenge"] = challenge.rstrip("=")

    return render_template(
        "dashboard/fido_setup.html",
        fido_token_form=fido_token_form,
        credential_create_options=registration_dict,
    )
