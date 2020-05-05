import uuid
import json
import secrets
import webauthn
from app.config import URL as SITE_URL
from urllib.parse import urlparse

from flask import render_template, flash, redirect, url_for, session
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import HiddenField, validators

from app.dashboard.base import dashboard_bp
from app.extensions import db
from app.log import LOG


class FidoTokenForm(FlaskForm):
    sk_assertion = HiddenField("sk_assertion", validators=[validators.DataRequired()])


@dashboard_bp.route("/fido_setup", methods=["GET", "POST"])
@login_required
def fido_setup():
    if current_user.fido_uuid is not None:
        flash("You have already registered your security key", "warning")
        return redirect(url_for("dashboard.index"))

    fido_token_form = FidoTokenForm()

    rp_id = urlparse(SITE_URL).hostname

    # Handling POST requests
    if fido_token_form.validate_on_submit():
        try:
            sk_assertion = json.loads(fido_token_form.sk_assertion.data)
        except Exception as e:
            flash('Key registration failed. Error: Invalid Payload', "warning")
            return redirect(url_for("dashboard.index"))
                    
        fido_uuid = session['fido_uuid']
        challenge = session['fido_challenge']

        fido_reg_response = webauthn.WebAuthnRegistrationResponse(
            rp_id,
            SITE_URL,
            sk_assertion,
            challenge,
            trusted_attestation_cert_required = False,
            none_attestation_permitted = True)

        try:
            fido_credential = fido_reg_response.verify()
        except Exception as e:
            flash('Key registration failed. Error: {}'.format(e), "warning")
            return redirect(url_for("dashboard.index"))

        current_user.fido_pk = fido_uuid
        current_user.fido_uuid = str(fido_credential.public_key, "utf-8")
        current_user.fido_credential_id = str(fido_credential.credential_id, "utf-8")
        db.session.commit()

        flash("Security key has been activated", "success")

        return redirect(url_for("dashboard.index"))
    
    # Prepare infomation for key registration process
    fido_uuid = str(uuid.uuid4())
    challenge = secrets.token_urlsafe(32)

    credential_create_options = webauthn.WebAuthnMakeCredentialOptions(
        challenge, 'Simple Login', rp_id, fido_uuid,
        current_user.email, current_user.name, False, attestation='none')

    # Don't think this one should be used, but it's not configurable by arguments
    # https://www.w3.org/TR/webauthn/#sctn-location-extension
    registration_dict = credential_create_options.registration_dict
    del registration_dict['extensions']['webauthn.loc']

    session['fido_uuid'] = fido_uuid
    session['fido_challenge'] = challenge.rstrip('=')

    return render_template(
        "dashboard/fido_setup.html", fido_token_form=fido_token_form, 
        credential_create_options=registration_dict
    )
