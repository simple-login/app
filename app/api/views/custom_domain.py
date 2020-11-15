from flask import g
from flask import jsonify

from app.api.base import api_bp, require_api_auth
from app.models import CustomDomain


def custom_domain_to_dict(custom_domain: CustomDomain):
    return {
        "id": custom_domain.id,
        "domain": custom_domain.domain,
        "verified": custom_domain.verified,
    }


@api_bp.route("/custom_domains", methods=["GET"])
@require_api_auth
def get_custom_domains():
    user = g.user
    custom_domains = CustomDomain.filter_by(user_id=user.id).all()

    return jsonify(custom_domains=[custom_domain_to_dict(cd) for cd in custom_domains])
