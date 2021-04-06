import csv
from io import StringIO

from flask import g
from flask import jsonify
from flask import make_response

from app.api.base import api_bp, require_api_auth
from app.models import Alias, Client, CustomDomain


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
    user = g.user

    data = [["alias", "note", "enabled", "mailboxes"]]
    for alias in Alias.filter_by(user_id=user.id).all():  # type: Alias
        # Always put the main mailbox first
        # It is seen a primary while importing
        alias_mailboxes = alias.mailboxes
        alias_mailboxes.insert(
            0, alias_mailboxes.pop(alias_mailboxes.index(alias.mailbox))
        )

        mailboxes = " ".join([mailbox.email for mailbox in alias_mailboxes])
        data.append([alias.email, alias.note, alias.enabled, mailboxes])

    si = StringIO()
    cw = csv.writer(si)
    cw.writerows(data)
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=aliases.csv"
    output.headers["Content-type"] = "text/csv"
    return output
