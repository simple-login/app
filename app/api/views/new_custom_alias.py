from flask import g
from flask import jsonify, request
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.log import LOG
from app.models import GenEmail, AliasUsedOn
from app.utils import convert_to_id


@api_bp.route("/alias/custom/new", methods=["POST"])
@cross_origin()
@verify_api_key
def new_custom_alias():
    """
    Create a new custom alias
    Input:
        alias_prefix, for ex "www_groupon_com"
        alias_suffix, either .random_letters@simplelogin.co or @my-domain.com
        optional "hostname" in args
    Output:
        201 if success
        409 if alias already exists

    """
    user = g.user
    if not user.can_create_new_custom_alias():
        LOG.d("user %s cannot create custom alias", user)
        return jsonify(error="no more quota for custom alias"), 400

    user_custom_domains = [cd.domain for cd in user.verified_custom_domains()]
    hostname = request.args.get("hostname")

    data = request.get_json()
    alias_prefix = data["alias_prefix"]
    alias_suffix = data["alias_suffix"]

    # make sure alias_prefix is more than 3 chars
    alias_prefix = alias_prefix.strip()
    alias_prefix = convert_to_id(alias_prefix)
    if not alias_prefix:  # should be checked on frontend
        LOG.d("user %s submits empty alias prefix %s", user, alias_prefix)
        return jsonify(error="alias prefix cannot be empty"), 400

    # make sure alias_suffix is either .random_letters@simplelogin.co or @my-domain.com
    alias_suffix = alias_suffix.strip()
    if alias_suffix.startswith("@"):
        custom_domain = alias_suffix[1:]
        if custom_domain not in user_custom_domains:
            LOG.d("user %s submits wrong custom domain %s ", user, custom_domain)
            return jsonify(error="error"), 400
    else:
        if not alias_suffix.startswith("."):
            LOG.d("user %s submits wrong alias suffix %s", user, alias_suffix)
            return jsonify(error="error"), 400
        if not alias_suffix.endswith(EMAIL_DOMAIN):
            LOG.d("user %s submits wrong alias suffix %s", user, alias_suffix)
            return jsonify(error="error"), 400

        random_letters = alias_suffix[1 : alias_suffix.find("@")]
        if len(random_letters) < 5:
            LOG.d("user %s submits wrong alias suffix %s", user, alias_suffix)
            return jsonify(error="error"), 400

    full_alias = alias_prefix + alias_suffix
    if GenEmail.get_by(email=full_alias):
        LOG.d("full alias already used %s", full_alias)
        return jsonify(error=f"alias {full_alias} already exists"), 409

    gen_email = GenEmail.create(user_id=user.id, email=full_alias)
    db.session.commit()

    if hostname:
        AliasUsedOn.create(gen_email_id=gen_email.id, hostname=hostname)
        db.session.commit()

    return jsonify(alias=full_alias), 201
