from flask import g
from flask import jsonify

from app.api.base import api_bp, require_api_auth
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
    custom_domains = CustomDomain.filter_by(user_id=user.id).all()

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
