import csv
from io import StringIO

from flask import g
from flask import jsonify
from flask import make_response

from app.api.base import api_bp, require_api_auth
from app.models import Alias, Client, CustomDomain
from app.alias_utils import alias_export_csv


@api_bp.route("/export/data", methods=["GET"])
@require_api_auth
def export_data():
    """
    Get user data
    Output:
        Alias, custom domain and app info

    """
    user = g.user

    data = {
        "email": user.email,
        "name": user.name,
        "aliases": [],
        "apps": [],
        "custom_domains": [],
    }

    for alias in Alias.filter_by(user_id=user.id).all():  # type: Alias
        data["aliases"].append(dict(email=alias.email, enabled=alias.enabled))

    for custom_domain in CustomDomain.filter_by(user_id=user.id).all():
        data["custom_domains"].append(custom_domain.domain)

    for app in Client.filter_by(user_id=user.id):  # type: Client
        data["apps"].append(dict(name=app.name, home_url=app.home_url))

    return jsonify(data)


@api_bp.route("/export/aliases", methods=["GET"])
@require_api_auth
def export_aliases():
    """
    Get user aliases as importable CSV file
    Output:
        Importable CSV file

    """
    return alias_export_csv(g.user)
