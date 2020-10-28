from flask import jsonify, g

from app.api.base import api_bp, require_api_auth
from app.models import User, AliasGeneratorEnum


def setting_to_dict(user: User):
    ret = {
        "notification": user.notification,
        "alias_generator": "word"
        if user.alias_generator == AliasGeneratorEnum.word
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
