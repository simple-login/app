"""Onboarding for developer when creating new app"""
from flask import render_template, flash, redirect, url_for
from flask_login import login_required, current_user

from app.developer.base import developer_bp
from app.models import Client


@developer_bp.route("/client/<int:client_id>/<step>")
@login_required
def handle_step(client_id, step):
    client = Client.get(client_id)
    if not client:
        flash("no such client", "warning")
        return redirect(url_for("developer.index"))

    if client.user_id != current_user.id:
        flash("you cannot see this client", "warning")
        return redirect(url_for("developer.index"))

    return render_template(
        f"developer/steps/{step}.html", client_id=client_id, client=client
    )
