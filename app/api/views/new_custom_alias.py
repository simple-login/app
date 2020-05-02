from flask import g
from flask import jsonify, request
from flask_cors import cross_origin
from itsdangerous import SignatureExpired

from app.api.base import api_bp, require_api_auth
from app.api.serializer import serialize_alias_info, get_alias_info
from app.config import MAX_NB_EMAIL_FREE_PLAN, ALIAS_DOMAINS
from app.dashboard.views.custom_alias import verify_prefix_suffix, signer
from app.extensions import db
from app.log import LOG
from app.models import Alias, AliasUsedOn, User, CustomDomain
from app.utils import convert_to_id


@api_bp.route("/alias/custom/new", methods=["POST"])
@cross_origin()
@require_api_auth
def new_custom_alias():
    """
    Create a new custom alias
    Input:
        alias_prefix, for ex "www_groupon_com"
        alias_suffix, either .random_letters@simplelogin.co or @my-domain.com
        optional "hostname" in args
        optional "note"
    Output:
        201 if success
        409 if the alias already exists

    """
    LOG.warning("/alias/custom/new is obsolete")
    user: User = g.user
    if not user.can_create_new_alias():
        LOG.d("user %s cannot create any custom alias", user)
        return (
            jsonify(
                error="You have reached the limitation of a free account with the maximum of "
                f"{MAX_NB_EMAIL_FREE_PLAN} aliases, please upgrade your plan to create more aliases"
            ),
            400,
        )

    hostname = request.args.get("hostname")

    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    alias_prefix = data.get("alias_prefix", "").strip()
    alias_suffix = data.get("alias_suffix", "").strip()
    note = data.get("note")
    alias_prefix = convert_to_id(alias_prefix)

    if not verify_prefix_suffix(user, alias_prefix, alias_suffix):
        return jsonify(error="wrong alias prefix or suffix"), 400

    full_alias = alias_prefix + alias_suffix
    if Alias.get_by(email=full_alias):
        LOG.d("full alias already used %s", full_alias)
        return jsonify(error=f"alias {full_alias} already exists"), 409

    alias = Alias.create(
        user_id=user.id, email=full_alias, mailbox_id=user.default_mailbox_id, note=note
    )

    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        if alias_domain not in ALIAS_DOMAINS:
            domain = CustomDomain.get_by(domain=alias_domain)
            LOG.d("set alias %s to domain %s", full_alias, domain)
            alias.custom_domain_id = domain.id

    db.session.commit()

    if hostname:
        AliasUsedOn.create(alias_id=alias.id, hostname=hostname, user_id=alias.user_id)
        db.session.commit()

    return jsonify(alias=full_alias, **serialize_alias_info(get_alias_info(alias))), 201


@api_bp.route("/v2/alias/custom/new", methods=["POST"])
@cross_origin()
@require_api_auth
def new_custom_alias_v2():
    """
    Create a new custom alias
    Same as v1 but signed_suffix is actually the suffix with signature, e.g.
    .random_word@SL.co.Xq19rQ.s99uWQ7jD1s5JZDZqczYI5TbNNU
    Input:
        alias_prefix, for ex "www_groupon_com"
        signed_suffix, either .random_letters@simplelogin.co or @my-domain.com
        optional "hostname" in args
        optional "note"
    Output:
        201 if success
        409 if the alias already exists

    """
    user: User = g.user
    if not user.can_create_new_alias():
        LOG.d("user %s cannot create any custom alias", user)
        return (
            jsonify(
                error="You have reached the limitation of a free account with the maximum of "
                f"{MAX_NB_EMAIL_FREE_PLAN} aliases, please upgrade your plan to create more aliases"
            ),
            400,
        )

    hostname = request.args.get("hostname")

    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    alias_prefix = data.get("alias_prefix", "").strip()
    signed_suffix = data.get("signed_suffix", "").strip()
    note = data.get("note")
    alias_prefix = convert_to_id(alias_prefix)

    # hypothesis: user will click on the button in the 300 secs
    try:
        alias_suffix = signer.unsign(signed_suffix, max_age=300).decode()
    except SignatureExpired:
        LOG.error("Alias creation time expired")
        return jsonify(error="alias creation is expired, please try again"), 400
    except Exception:
        LOG.error("Alias suffix is tampered, user %s", user)
        return jsonify(error="Tampered suffix"), 400

    if not verify_prefix_suffix(user, alias_prefix, alias_suffix):
        return jsonify(error="wrong alias prefix or suffix"), 400

    full_alias = alias_prefix + alias_suffix
    if Alias.get_by(email=full_alias):
        LOG.d("full alias already used %s", full_alias)
        return jsonify(error=f"alias {full_alias} already exists"), 409

    alias = Alias.create(
        user_id=user.id, email=full_alias, mailbox_id=user.default_mailbox_id, note=note
    )

    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        if alias_domain not in ALIAS_DOMAINS:
            domain = CustomDomain.get_by(domain=alias_domain)
            LOG.d("set alias %s to domain %s", full_alias, domain)
            alias.custom_domain_id = domain.id

    db.session.commit()

    if hostname:
        AliasUsedOn.create(alias_id=alias.id, hostname=hostname, user_id=alias.user_id)
        db.session.commit()

    return jsonify(alias=full_alias, **serialize_alias_info(get_alias_info(alias))), 201
