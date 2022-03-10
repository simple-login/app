from flask import render_template
from flask_login import login_required

from app.discover.base import discover_bp
from app.models import Client


@discover_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    clients = Client.filter_by(approved=True).all()
    return render_template("discover/index.html", clients=clients)
