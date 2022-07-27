import tldextract
from flask import jsonify, request, g
from sqlalchemy import desc

from app.alias_suffix import get_alias_suffixes
from app.api.base import api_bp, require_api_auth
from app.db import Session
from app.log import LOG
from app.models import AliasUsedOn, Alias, User
from app.utils import convert_to_id


@api_bp.route("/v4/alias/options")
@require_api_auth
def options_v4():
    """
    Return what options user has when creating new alias.
    Same as v3 but return time-based signed-suffix in addition to suffix. To be used with /v2/alias/custom/new
    Input:
        a valid api-key in "Authentication" header and
        optional "hostname" in args
    Output: cf README
        can_create: bool
        suffixes: [[suffix, signed_suffix]]
        prefix_suggestion: str
        recommendation: Optional dict
            alias: str
            hostname: str


    """
    user = g.user
    hostname = request.args.get("hostname")

    ret = {
        "can_create": user.can_create_new_alias(),
        "suffixes": [],
        "prefix_suggestion": "",
    }

    # recommendation alias if exist
    if hostname:
        # put the latest used alias first
        q = (
            Session.query(AliasUsedOn, Alias, User)
            .filter(
                AliasUsedOn.alias_id == Alias.id,
                Alias.user_id == user.id,
                AliasUsedOn.hostname == hostname,
            )
            .order_by(desc(AliasUsedOn.created_at))
        )

        r = q.first()
        if r:
            _, alias, _ = r
            LOG.d("found alias %s %s %s", alias, hostname, user)
            ret["recommendation"] = {"alias": alias.email, "hostname": hostname}

    # custom alias suggestion and suffix
    if hostname:
        # keep only the domain name of hostname, ignore TLD and subdomain
        # for ex www.groupon.com -> groupon
        ext = tldextract.extract(hostname)
        prefix_suggestion = ext.domain
        prefix_suggestion = convert_to_id(prefix_suggestion)
        ret["prefix_suggestion"] = prefix_suggestion

    suffixes = get_alias_suffixes(user)

    # custom domain should be put first
    ret["suffixes"] = list([suffix.suffix, suffix.signed_suffix] for suffix in suffixes)

    return jsonify(ret)


@api_bp.route("/v5/alias/options")
@require_api_auth
def options_v5():
    """
    Return what options user has when creating new alias.
    Same as v4 but uses a better format. To be used with /v2/alias/custom/new
    Input:
        a valid api-key in "Authentication" header and
        optional "hostname" in args
    Output: cf README
        can_create: bool
        suffixes: [
            {
                suffix: "suffix",
                signed_suffix: "signed_suffix",
                is_custom: true,
                is_premium: false
            }
        ]
        prefix_suggestion: str
        recommendation: Optional dict
            alias: str
            hostname: str


    """
    user = g.user
    hostname = request.args.get("hostname")

    ret = {
        "can_create": user.can_create_new_alias(),
        "suffixes": [],
        "prefix_suggestion": "",
    }

    # recommendation alias if exist
    if hostname:
        # put the latest used alias first
        q = (
            Session.query(AliasUsedOn, Alias, User)
            .filter(
                AliasUsedOn.alias_id == Alias.id,
                Alias.user_id == user.id,
                AliasUsedOn.hostname == hostname,
            )
            .order_by(desc(AliasUsedOn.created_at))
        )

        r = q.first()
        if r:
            _, alias, _ = r
            LOG.d("found alias %s %s %s", alias, hostname, user)
            ret["recommendation"] = {"alias": alias.email, "hostname": hostname}

    # custom alias suggestion and suffix
    if hostname:
        # keep only the domain name of hostname, ignore TLD and subdomain
        # for ex www.groupon.com -> groupon
        ext = tldextract.extract(hostname)
        prefix_suggestion = ext.domain
        prefix_suggestion = convert_to_id(prefix_suggestion)
        ret["prefix_suggestion"] = prefix_suggestion

    suffixes = get_alias_suffixes(user)

    # custom domain should be put first
    ret["suffixes"] = [
        {
            "suffix": suffix.suffix,
            "signed_suffix": suffix.signed_suffix,
            "is_custom": suffix.is_custom,
            "is_premium": suffix.is_premium,
        }
        for suffix in suffixes
    ]

    return jsonify(ret)
