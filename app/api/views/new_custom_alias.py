from flask import g
from flask import jsonify, request
from itsdangerous import SignatureExpired

from app.alias_utils import check_alias_prefix
from app.api.base import api_bp, require_api_auth
from app.api.serializer import (
    serialize_alias_info,
    get_alias_info,
    serialize_alias_info_v2,
    get_alias_info_v2,
)
from app.config import MAX_NB_EMAIL_FREE_PLAN
from app.dashboard.views.custom_alias import verify_prefix_suffix, signer
from app.extensions import db, limiter
from app.log import LOG
from app.models import (
    Alias,
    AliasUsedOn,
    User,
    CustomDomain,
    DeletedAlias,
    DomainDeletedAlias,
    Mailbox,
    AliasMailbox,
)
from app.utils import convert_to_id


@api_bp.route("/alias/custom/new", methods=["POST"])
@limiter.limit("5/minute")
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

    alias_prefix = data.get("alias_prefix", "").strip().lower().replace(" ", "")
    alias_suffix = data.get("alias_suffix", "").strip().lower().replace(" ", "")
    note = data.get("note")
    alias_prefix = convert_to_id(alias_prefix)

    if not verify_prefix_suffix(user, alias_prefix, alias_suffix):
        return jsonify(error="wrong alias prefix or suffix"), 400

    full_alias = alias_prefix + alias_suffix
    if (
        Alias.get_by(email=full_alias)
        or DeletedAlias.get_by(email=full_alias)
        or DomainDeletedAlias.get_by(email=full_alias)
    ):
        LOG.d("full alias already used %s", full_alias)
        return jsonify(error=f"alias {full_alias} already exists"), 409

    alias = Alias.create(
        user_id=user.id, email=full_alias, mailbox_id=user.default_mailbox_id, note=note
    )

    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        domain = CustomDomain.get_by(domain=alias_domain)
        if domain:
            LOG.d("set alias %s to domain %s", full_alias, domain)
            alias.custom_domain_id = domain.id

    db.session.commit()

    if hostname:
        AliasUsedOn.create(alias_id=alias.id, hostname=hostname, user_id=alias.user_id)
        db.session.commit()

    return jsonify(alias=full_alias, **serialize_alias_info(get_alias_info(alias))), 201


@api_bp.route("/v2/alias/custom/new", methods=["POST"])
@limiter.limit("5/minute")
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

    alias_prefix = data.get("alias_prefix", "").strip().lower().replace(" ", "")
    signed_suffix = data.get("signed_suffix", "").strip()
    note = data.get("note")
    alias_prefix = convert_to_id(alias_prefix)

    # hypothesis: user will click on the button in the 600 secs
    try:
        alias_suffix = signer.unsign(signed_suffix, max_age=600).decode()
    except SignatureExpired:
        LOG.warning("Alias creation time expired for %s", user)
        return jsonify(error="Alias creation time is expired, please retry"), 412
    except Exception:
        LOG.warning("Alias suffix is tampered, user %s", user)
        return jsonify(error="Tampered suffix"), 400

    if not verify_prefix_suffix(user, alias_prefix, alias_suffix):
        return jsonify(error="wrong alias prefix or suffix"), 400

    full_alias = alias_prefix + alias_suffix
    if (
        Alias.get_by(email=full_alias)
        or DeletedAlias.get_by(email=full_alias)
        or DomainDeletedAlias.get_by(email=full_alias)
    ):
        LOG.d("full alias already used %s", full_alias)
        return jsonify(error=f"alias {full_alias} already exists"), 409

    custom_domain_id = None
    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        domain = CustomDomain.get_by(domain=alias_domain)

        # check if the alias is currently in the domain trash
        if domain and DomainDeletedAlias.get_by(domain_id=domain.id, email=full_alias):
            LOG.d(f"Alias {full_alias} is currently in the {domain.domain} trash. ")
            return jsonify(error=f"alias {full_alias} in domain trash"), 409

        if domain:
            custom_domain_id = domain.id

    alias = Alias.create(
        user_id=user.id,
        email=full_alias,
        mailbox_id=user.default_mailbox_id,
        note=note,
        custom_domain_id=custom_domain_id,
    )

    db.session.commit()

    if hostname:
        AliasUsedOn.create(alias_id=alias.id, hostname=hostname, user_id=alias.user_id)
        db.session.commit()

    return (
        jsonify(alias=full_alias, **serialize_alias_info_v2(get_alias_info_v2(alias))),
        201,
    )


@api_bp.route("/v3/alias/custom/new", methods=["POST"])
@limiter.limit("5/minute")
@require_api_auth
def new_custom_alias_v3():
    """
    Create a new custom alias
    Same as v2 but accept a list of mailboxes as input
    Input:
        alias_prefix, for ex "www_groupon_com"
        signed_suffix, either .random_letters@simplelogin.co or @my-domain.com
        mailbox_ids: list of int
        optional "hostname" in args
        optional "note"
        optional "name"

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

    alias_prefix = data.get("alias_prefix", "").strip().lower().replace(" ", "")
    signed_suffix = data.get("signed_suffix", "").strip()
    mailbox_ids = data.get("mailbox_ids")
    note = data.get("note")
    name = data.get("name")
    alias_prefix = convert_to_id(alias_prefix)

    if not check_alias_prefix(alias_prefix):
        return jsonify(error="alias prefix format problem"), 400

    # check if mailbox is not tempered with
    mailboxes = []
    for mailbox_id in mailbox_ids:
        mailbox = Mailbox.get(mailbox_id)
        if not mailbox or mailbox.user_id != user.id or not mailbox.verified:
            return jsonify(error="Errors with Mailbox"), 400
        mailboxes.append(mailbox)

    if not mailboxes:
        return jsonify(error="At least one mailbox must be selected"), 400

    # hypothesis: user will click on the button in the 600 secs
    try:
        alias_suffix = signer.unsign(signed_suffix, max_age=600).decode()
    except SignatureExpired:
        LOG.warning("Alias creation time expired for %s", user)
        return jsonify(error="Alias creation time is expired, please retry"), 412
    except Exception:
        LOG.warning("Alias suffix is tampered, user %s", user)
        return jsonify(error="Tampered suffix"), 400

    if not verify_prefix_suffix(user, alias_prefix, alias_suffix):
        return jsonify(error="wrong alias prefix or suffix"), 400

    full_alias = alias_prefix + alias_suffix
    if (
        Alias.get_by(email=full_alias)
        or DeletedAlias.get_by(email=full_alias)
        or DomainDeletedAlias.get_by(email=full_alias)
    ):
        LOG.d("full alias already used %s", full_alias)
        return jsonify(error=f"alias {full_alias} already exists"), 409

    custom_domain_id = None
    if alias_suffix.startswith("@"):
        alias_domain = alias_suffix[1:]
        domain = CustomDomain.get_by(domain=alias_domain)
        if domain:
            custom_domain_id = domain.id

    alias = Alias.create(
        user_id=user.id,
        email=full_alias,
        note=note,
        name=name or None,
        mailbox_id=mailboxes[0].id,
        custom_domain_id=custom_domain_id,
    )
    db.session.flush()

    for i in range(1, len(mailboxes)):
        AliasMailbox.create(
            alias_id=alias.id,
            mailbox_id=mailboxes[i].id,
        )

    db.session.commit()

    if hostname:
        AliasUsedOn.create(alias_id=alias.id, hostname=hostname, user_id=alias.user_id)
        db.session.commit()

    return (
        jsonify(alias=full_alias, **serialize_alias_info_v2(get_alias_info_v2(alias))),
        201,
    )
