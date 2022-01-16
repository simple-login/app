from flask import g, request
from flask import jsonify

from app.api.base import api_bp, require_api_auth
from app.db import Session
from app.models import CustomDomain, DomainDeletedAlias, Mailbox, DomainMailbox


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
        if mailbox_ids:
            # check if mailbox is not tempered with
            mailboxes = []
            for mailbox_id in mailbox_ids:
                mailbox = Mailbox.get(mailbox_id)
                if not mailbox or mailbox.user_id != user.id or not mailbox.verified:
                    return jsonify(error="Forbidden"), 400
                mailboxes.append(mailbox)

            # first remove all existing domain-mailboxes links
            DomainMailbox.filter_by(domain_id=custom_domain.id).delete()
            Session.flush()

            for mailbox in mailboxes:
                DomainMailbox.create(domain_id=custom_domain.id, mailbox_id=mailbox.id)

            changed = True

    if changed:
        Session.commit()

    # refresh
    custom_domain = CustomDomain.get(custom_domain_id)
    return jsonify(custom_domain=custom_domain_to_dict(custom_domain)), 200
