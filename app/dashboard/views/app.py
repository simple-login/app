from app.db import Session

"""
List of apps that user has used via the "Sign in with SimpleLogin"
"""

from flask import render_template, request, flash, redirect
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

    if request.method == "POST":
        client_user_id = request.form.get("client-user-id")
        client_user = ClientUser.get(client_user_id)
        if not client_user or client_user.user_id != current_user.id:
            flash(
                "Unknown error, sorry for the inconvenience, refresh the page", "error"
            )
            return redirect(request.url)

        client = client_user.client
        ClientUser.delete(client_user_id)
        Session.commit()

        flash(f"Link with {client.name}  has been removed", "success")
        return redirect(request.url)

    return render_template(
        "dashboard/app.html",
        client_users=client_users,
    )
