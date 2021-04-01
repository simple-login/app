"""
List of apps that user has used via the "Sign in with SimpleLogin"
"""

from flask import render_template
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app.dashboard.base import dashboard_bp
from app.models import (
    ClientUser,
)


@dashboard_bp.route("/app", methods=["GET", "POST"])
@login_required
def app_route():
    client_users = (
        ClientUser.filter_by(user_id=current_user.id)
        .options(joinedload(ClientUser.client))
        .options(joinedload(ClientUser.alias))
        .all()
    )

    sorted(client_users, key=lambda cu: cu.client.name)

    return render_template(
        "dashboard/app.html",
        client_users=client_users,
    )
