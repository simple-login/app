"""List of clients"""
from flask import render_template, request, flash, redirect, url_for
from flask_login import current_user, login_required

from app.developer.base import developer_bp
from app.extensions import db
from app.log import LOG
from app.models import Client


@developer_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        if request.form.get("form-name") == "switch-client-publish":
            client_id = int(request.form.get("client-id"))
            client = Client.get(client_id)

            if client.user_id != current_user.id:
                flash("You cannot modify this client", "warning")
            else:
                client.published = not client.published
                db.session.commit()
                LOG.d("Switch client.published %s", client)

                if client.published:
                    flash(
                        f"Client {client.name} has been published on Discover",
                        "success",
                    )
                else:
                    flash(f"Client {client.name} has been un-published", "success")

        return redirect(url_for("developer.index"))

    clients = Client.filter_by(user_id=current_user.id).all()

    return render_template("developer/index.html", clients=clients)
