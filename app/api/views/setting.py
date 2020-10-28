from flask import jsonify, g, request

from app.api.base import api_bp, require_api_auth
from app.extensions import db
from app.log import LOG
from app.models import User, AliasGeneratorEnum, SLDomain, CustomDomain


def setting_to_dict(user: User):
    ret = {
        "notification": user.notification,
        "alias_generator": "word"
        if user.alias_generator == AliasGeneratorEnum.word.value
        else "uuid",
        "random_alias_default_domain": user.default_random_alias_domain(),
    }

    return ret


@api_bp.route("/setting")
@require_api_auth
def get_setting():
    """
    Return user setting
    """
    user = g.user

    return jsonify(setting_to_dict(user))


@api_bp.route("/setting", methods=["PATCH"])
@require_api_auth
def update_setting():
    """
    Update user setting
    Input:
    - notification: bool
    - alias_generator: word|uuid
    - random_alias_default_domain: str
    """
    user = g.user
    data = request.get_json() or {}

    if "notification" in data:
        user.notification = data["notification"]

    if "alias_generator" in data:
        alias_generator = data["alias_generator"]
        if alias_generator not in ["word", "uuid"]:
            return jsonify(error="Invalid alias_generator"), 400

        if alias_generator == "word":
            user.alias_generator = AliasGeneratorEnum.word.value
        else:
            user.alias_generator = AliasGeneratorEnum.uuid.value

    if "random_alias_default_domain" in data:
        default_domain = data["random_alias_default_domain"]
        sl_domain: SLDomain = SLDomain.get_by(domain=default_domain)
        if sl_domain:
            if sl_domain.premium_only and not user.is_premium():
                return jsonify(error="You cannot use this domain"), 400

            # make sure only default_random_alias_domain_id or default_random_alias_public_domain_id is set
            user.default_random_alias_public_domain_id = sl_domain.id
            user.default_random_alias_domain_id = None
        else:
            custom_domain = CustomDomain.get_by(domain=default_domain)
            if not custom_domain:
                return jsonify(error="invalid domain"), 400

            # sanity check
            if custom_domain.user_id != user.id or not custom_domain.verified:
                LOG.exception("%s cannot use domain %s", user, default_domain)
                return jsonify(error="invalid domain"), 400
            else:
                # make sure only default_random_alias_domain_id or
                # default_random_alias_public_domain_id is set
                user.default_random_alias_domain_id = custom_domain.id
                user.default_random_alias_public_domain_id = None

    db.session.commit()
    return jsonify(setting_to_dict(user))


@api_bp.route("/setting/domains")
@require_api_auth
def get_available_domains_for_random_alias():
    """
    Available domains for random alias
    """
    user = g.user

    ret = [
        (is_sl, domain) for is_sl, domain in user.available_domains_for_random_alias()
    ]

    return jsonify(ret)
