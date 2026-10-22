"""List of clients"""

from flask import render_template
from flask_login import current_user, login_required

from app import config
from app.developer.base import developer_bp
from app.models import Client


@developer_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    clients = Client.filter_by(user_id=current_user.id).all()

    return render_template(
        "developer/index.html",
        clients=clients,
        allow_new_clients=config.ALLOW_NEW_OAUTH_CLIENTS,
    )
