import tldextract
from flask import g
from flask import jsonify, request

from app import parallel_limiter
from app.alias_suffix import get_alias_suffixes
from app.api.base import api_bp, require_api_auth
from app.api.serializer import (
    get_alias_info_v2,
    serialize_alias_info_v2,
)
from app.config import MAX_NB_EMAIL_FREE_PLAN, ALIAS_LIMIT
from app.db import Session
from app.errors import AliasInTrashError
from app.extensions import limiter
from app.log import LOG
from app.models import Alias, AliasUsedOn, AliasGeneratorEnum
from app.utils import convert_to_id


@api_bp.route("/alias/random/new", methods=["POST"])
@limiter.limit(ALIAS_LIMIT)
@require_api_auth
@parallel_limiter.lock(name="alias_creation")
def new_random_alias():
    """
    Create a new random alias
    Input:
        (Optional) note
    Output:
        201 if success

    """
    user = g.user
    if not user.can_create_new_alias():
        LOG.d("user %s cannot create new random alias", user)
        return (
            jsonify(
                error=f"You have reached the limitation of a free account with the maximum of "
                f"{MAX_NB_EMAIL_FREE_PLAN} aliases, please upgrade your plan to create more aliases"
            ),
            400,
        )

    note = None
    data = request.get_json(silent=True)
    if data:
        note = data.get("note")

    alias = None

    # custom alias suggestion and suffix
    hostname = request.args.get("hostname")
    if hostname and user.include_website_in_one_click_alias:
        LOG.d("Use %s to create new alias", hostname)
        # keep only the domain name of hostname, ignore TLD and subdomain
        # for ex www.groupon.com -> groupon
        ext = tldextract.extract(hostname)
        prefix_suggestion = ext.domain
        prefix_suggestion = convert_to_id(prefix_suggestion)

        suffixes = get_alias_suffixes(user)
        # use the first suffix
        suggested_alias = prefix_suggestion + suffixes[0].suffix

        alias = Alias.get_by(email=suggested_alias)

        # cannot use this alias as it belongs to another user
        if alias and not alias.user_id == user.id:
            LOG.d("%s belongs to another user", alias)
            alias = None
        elif alias and alias.user_id == user.id:
            # make sure alias was created for this website
            if AliasUsedOn.get_by(
                alias_id=alias.id, hostname=hostname, user_id=alias.user_id
            ):
                LOG.d("Use existing alias %s", alias)
            else:
                LOG.d("%s wasn't created for this website %s", alias, hostname)
                alias = None
        elif not alias:
            LOG.d("create new alias %s", suggested_alias)
            try:
                alias = Alias.create(
                    user_id=user.id,
                    email=suggested_alias,
                    note=note,
                    mailbox_id=user.default_mailbox_id,
                    commit=True,
                )
            except AliasInTrashError:
                LOG.i("Alias %s is in trash", suggested_alias)
                alias = None

    if not alias:
        scheme = user.alias_generator
        mode = request.args.get("mode")
        if mode:
            if mode == "word":
                scheme = AliasGeneratorEnum.word.value
            elif mode == "uuid":
                scheme = AliasGeneratorEnum.uuid.value
            else:
                return jsonify(error=f"{mode} must be either word or uuid"), 400

        alias = Alias.create_new_random(user=user, scheme=scheme, note=note)
        Session.commit()

    if hostname and not AliasUsedOn.get_by(alias_id=alias.id, hostname=hostname):
        AliasUsedOn.create(
            alias_id=alias.id, hostname=hostname, user_id=alias.user_id, commit=True
        )

    return (
        jsonify(alias=alias.email, **serialize_alias_info_v2(get_alias_info_v2(alias))),
        201,
    )
