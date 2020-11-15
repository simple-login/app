from flask import g
from flask import jsonify

from app.api.base import api_bp, require_api_auth
from app.models import CustomDomain, DomainDeletedAlias


def custom_domain_to_dict(custom_domain: CustomDomain):
    return {
        "id": custom_domain.id,
        "domain": custom_domain.domain,
        "verified": custom_domain.verified,
        "nb_alias": custom_domain.nb_alias(),
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
                "creation_timestamp": dda.created_at.timestamp,
            }
            for dda in domain_deleted_aliases
        ]
    )
