from flask import jsonify, request, g
from flask_cors import cross_origin

from app.api.base import api_bp, verify_api_key
from app.config import EMAIL_DOMAIN
from app.extensions import db
from app.log import LOG
from app.models import AliasUsedOn, GenEmail, User
from app.utils import random_string


@api_bp.route("/alias/options")
@cross_origin()
@verify_api_key
def options():
    """
    Return what options user has when creating new alias.
    Input:
        a valid api-key in "Authentication" header and
        optional "hostname" in args
    Output: cf README
        optional recommendation:
        optional custom
        can_create_custom: boolean
        can_create_random: boolean
        existing: array of existing aliases

    """
    user = g.user
    hostname = request.args.get("hostname")

    ret = {
        "existing": [ge.email for ge in GenEmail.query.filter_by(user_id=user.id)],
        "can_create_custom": user.can_create_new_custom_alias(),
        "can_create_random": user.can_create_new_random_alias(),
    }

    # recommendation alias if exist
    if hostname:
        q = db.session.query(AliasUsedOn, GenEmail, User).filter(
            AliasUsedOn.gen_email_id == GenEmail.id,
            GenEmail.user_id == user.id,
            AliasUsedOn.hostname == hostname,
        )

        r = q.first()
        if r:
            _, alias, _ = r
            LOG.d("found alias %s %s %s", alias, hostname, user)
            ret["recommendation"] = {"alias": alias.email, "hostname": hostname}

    # custom alias suggestion and suffix
    if user.can_create_new_custom_alias():
        ret["custom"] = {}
        if hostname:
            ret["custom"]["suggestion"] = hostname.replace(".", "_")
        else:
            ret["custom"]["suggestion"] = ""

        # maybe better to make sure the suffix is never used before
        # but this is ok as there's a check when creating a new custom alias
        ret["custom"]["suffixes"] = [f".{random_string(6)}@{EMAIL_DOMAIN}"]

        for custom_domain in user.verified_custom_domains():
            ret["custom"]["suffixes"].append("@" + custom_domain.domain)

        # custom domain should be put first
        ret["custom"]["suffixes"] = list(reversed(ret["custom"]["suffixes"]))

    return jsonify(ret)
