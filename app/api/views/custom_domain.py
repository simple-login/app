from flask import g, request
from flask import jsonify

from app.api.base import api_bp, require_api_auth
from app.custom_domain_utils import set_custom_domain_mailboxes
from app.db import Session
from app.extensions import limiter
from app.log import LOG
from app.models import CustomDomain, DomainDeletedAlias


def custom_domain_to_dict(custom_domain: CustomDomain):
    return {
        "id": custom_domain.id,
        "domain_name": custom_domain.domain,
        "is_verified": custom_domain.verified,
        "nb_alias": custom_domain.nb_alias(),
        "creation_date": custom_domain.created_at.format(),
        "creation_timestamp": custom_domain.created_at.timestamp,
        "catch_all": custom_domain.catch_all,
        "name": custom_domain.name,
        "random_prefix_generation": custom_domain.random_prefix_generation,
        "mailboxes": [
            {"id": mb.id, "email": mb.email} for mb in custom_domain.mailboxes
        ],
    }


@api_bp.route("/custom_domains", methods=["GET"])
@require_api_auth
def get_custom_domains():
    user = g.user
    custom_domains = CustomDomain.filter_by(
        user_id=user.id, is_sl_subdomain=False
    ).all()

    return jsonify(custom_domains=[custom_domain_to_dict(cd) for cd in custom_domains])


@api_bp.route("/custom_domains/<int:custom_domain_id>/trash", methods=["GET"])
@require_api_auth
def get_custom_domain_trash(custom_domain_id: int):
    user = g.user
    custom_domain = CustomDomain.get(custom_domain_id)
    if not custom_domain or custom_domain.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    domain_deleted_aliases = DomainDeletedAlias.filter_by(
        domain_id=custom_domain.id
    ).all()

    return jsonify(
        aliases=[
            {
                "alias": dda.email,
                "deletion_timestamp": dda.created_at.timestamp,
            }
            for dda in domain_deleted_aliases
        ]
    )


@api_bp.route("/custom_domains/<int:custom_domain_id>", methods=["PATCH"])
@require_api_auth
@limiter.limit("100/hour")
def update_custom_domain(custom_domain_id):
    """
    Update alias note
    Input:
        custom_domain_id: in url
    In body:
        catch_all (optional): boolean
        random_prefix_generation (optional): boolean
        name (optional): in body
        mailbox_ids (optional): array of mailbox_id
    Output:
        200
    """
    data = request.get_json()
    if not data:
        return jsonify(error="request body cannot be empty"), 400

    user = g.user
    custom_domain: CustomDomain = CustomDomain.get(custom_domain_id)

    if not custom_domain or custom_domain.user_id != user.id:
        return jsonify(error="Forbidden"), 403

    changed = False
    if "catch_all" in data:
        catch_all = data.get("catch_all")
        custom_domain.catch_all = catch_all
        changed = True

    if "random_prefix_generation" in data:
        random_prefix_generation = data.get("random_prefix_generation")
        custom_domain.random_prefix_generation = random_prefix_generation
        changed = True

    if "name" in data:
        name = data.get("name")
        custom_domain.name = name
        changed = True

    if "mailbox_ids" in data:
        mailbox_ids = [int(m_id) for m_id in data.get("mailbox_ids")]
        result = set_custom_domain_mailboxes(user.id, custom_domain, mailbox_ids)
        if result.success:
            changed = True
        else:
            LOG.info(
                f"Prevented from updating mailboxes [custom_domain_id={custom_domain.id}]: {result.reason.value}"
            )
            return jsonify(error="Forbidden"), 400

    if changed:
        Session.commit()

    # refresh
    custom_domain = CustomDomain.get(custom_domain_id)
    return jsonify(custom_domain=custom_domain_to_dict(custom_domain)), 200
