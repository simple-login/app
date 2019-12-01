import random

import arrow
from flask import jsonify, request
from flask_cors import cross_origin

from app.api.base import api_bp
from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.log import LOG
from app.models import ApiKey, AliasUsedOn, GenEmail, User, DeletedAlias
from app.utils import random_string


@api_bp.route("/alias/new", methods=["GET", "POST"])
@cross_origin()
def index():
    """
    the incoming request must provide a valid api-key in "Authentication" header and
    the payload must contain "hostname"
    """
    api_code = request.headers.get("Authentication")
    api_key = ApiKey.get_by(code=api_code)

    if not api_key:
        return jsonify(error="Wrong api key"), 401

    data = request.get_json()
    if not data:
        return jsonify(error="hostname must be provided")

    hostname = data.get("hostname")

    # Update api key stats
    api_key.last_used = arrow.now()
    api_key.times += 1
    db.session.commit()

    user = api_key.user

    q = db.session.query(AliasUsedOn, GenEmail, User).filter(
        AliasUsedOn.gen_email_id == GenEmail.id,
        GenEmail.user_id == user.id,
        AliasUsedOn.hostname == hostname,
    )

    r = q.first()
    if r:
        _, alias, _ = r
        LOG.d("found alias %s %s %s", alias, hostname, user)
        return jsonify(alias=alias.email)

    # use a custom alias for this user
    if user.is_premium():
        LOG.d("create new custom alias %s %s", hostname, user)

        # avoid too short custom email prefix
        if len(hostname) < 3:
            LOG.d("hostname %s too short", hostname)
            hostname = "default"

        # generate a custom email
        found = False
        while not found:
            email_suffix = random_string(6)
            email_prefix = hostname.replace(".", "_")
            full_email = f"{email_prefix}.{email_suffix}@{EMAIL_DOMAIN}"

            # check if email already exists. Very rare that an email is already used
            if GenEmail.get_by(email=full_email) or DeletedAlias.get_by(
                email=full_email
            ):
                LOG.warning("full_email already used %s. Retry", full_email)
            else:
                found = True

        gen_email = GenEmail.create(email=full_email, user_id=user.id, custom=True)
        db.session.flush()

        AliasUsedOn.create(gen_email_id=gen_email.id, hostname=hostname)
        db.session.commit()

        return jsonify(alias=full_email)
    else:
        # choose randomly from user non-custom alias
        aliases = db.session.query(GenEmail).filter(GenEmail.user_id == user.id).all()
        if aliases:
            alias = random.choice(aliases)
        else:
            LOG.d("user %s has no alias, create one", user)
            alias = GenEmail.create_new_gen_email(user.id)
            db.session.commit()

        AliasUsedOn.create(gen_email_id=alias.id, hostname=hostname)
        db.session.commit()

        return jsonify(alias=alias.email)
