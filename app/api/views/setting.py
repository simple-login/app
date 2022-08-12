import arrow
from flask import jsonify, g, request

from app.api.base import api_bp, require_api_auth
from app.db import Session
from app.log import LOG
from app.models import (
    User,
    AliasGeneratorEnum,
    SLDomain,
    CustomDomain,
    SenderFormatEnum,
    AliasSuffixEnum,
)
from app.proton.utils import perform_proton_account_unlink


def setting_to_dict(user: User):
    ret = {
        "notification": user.notification,
        "alias_generator": "word"
        if user.alias_generator == AliasGeneratorEnum.word.value
        else "uuid",
        "random_alias_default_domain": user.default_random_alias_domain(),
        # return the default sender format (AT) in case user uses a non-supported sender format
        "sender_format": SenderFormatEnum.get_name(user.sender_format)
        or SenderFormatEnum.AT.name,
        "random_alias_suffix": AliasSuffixEnum.get_name(user.random_alias_suffix),
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

    if "sender_format" in data:
        sender_format = data["sender_format"]
        if not SenderFormatEnum.has_name(sender_format):
            return jsonify(error="Invalid sender_format"), 400

        user.sender_format = SenderFormatEnum.get_value(sender_format)
        user.sender_format_updated_at = arrow.now()

    if "random_alias_suffix" in data:
        random_alias_suffix = data["random_alias_suffix"]
        if not AliasSuffixEnum.has_name(random_alias_suffix):
            return jsonify(error="Invalid random_alias_suffix"), 400

        user.random_alias_suffix = AliasSuffixEnum.get_value(random_alias_suffix)

    if "random_alias_default_domain" in data:
        default_domain = data["random_alias_default_domain"]
        sl_domain: SLDomain = SLDomain.get_by(domain=default_domain)
        if sl_domain:
            if sl_domain.premium_only and not user.is_premium():
                return jsonify(error="You cannot use this domain"), 400

            user.default_alias_public_domain_id = sl_domain.id
            user.default_alias_custom_domain_id = None
        else:
            custom_domain = CustomDomain.get_by(domain=default_domain)
            if not custom_domain:
                return jsonify(error="invalid domain"), 400

            # sanity check
            if custom_domain.user_id != user.id or not custom_domain.verified:
                LOG.w("%s cannot use domain %s", user, default_domain)
                return jsonify(error="invalid domain"), 400
            else:
                user.default_alias_custom_domain_id = custom_domain.id
                user.default_alias_public_domain_id = None

    Session.commit()
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


@api_bp.route("/v2/setting/domains")
@require_api_auth
def get_available_domains_for_random_alias_v2():
    """
    Available domains for random alias
    """
    user = g.user

    ret = [
        {"domain": domain, "is_custom": not is_sl}
        for is_sl, domain in user.available_domains_for_random_alias()
    ]

    return jsonify(ret)


@api_bp.route("/setting/unlink_proton_account", methods=["DELETE"])
@require_api_auth
def unlink_proton_account():
    user = g.user
    perform_proton_account_unlink(user)
    return jsonify({"ok": True})
