from io import BytesIO

from flask import request, render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, validators

from app import s3
from app.developer.base import developer_bp
from app.extensions import db
from app.log import LOG
from app.models import Client, RedirectUri, File
from app.utils import random_string


class EditClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])
    icon = FileField("Icon")
    home_url = StringField("Home Url")


@developer_bp.route("/clients/<client_id>", methods=["GET", "POST"])
@login_required
def client_detail(client_id):
    form = EditClientForm()

    client = Client.get(client_id)
    if not client:
        flash("no such client", "warning")
        return redirect(url_for("developer.index"))

    if client.user_id != current_user.id:
        flash("you cannot see this client", "warning")
        return redirect(url_for("developer.index"))

    if request.method == "POST":
        if form.validate():
            client.name = form.name.data
            client.home_url = form.home_url.data

            if form.icon.data:
                # todo: remove current icon if any
                # todo: handle remove icon
                file_path = random_string(30)
                file = File.create(path=file_path)

                s3.upload_from_bytesio(file_path, BytesIO(form.icon.data.read()))

                db.session.commit()
                LOG.d("upload file %s to s3", file)

                client.icon_id = file.id
                db.session.commit()

            uris = request.form.getlist("uri")

            # replace all uris. TODO: optimize this?
            for redirect_uri in client.redirect_uris:
                redirect_uri.delete()

            for uri in uris:
                RedirectUri.create(client_id=client_id, uri=uri)

            db.session.commit()

            flash(f"client {client.name} has been updated", "success")

            return redirect(url_for("developer.client_detail", client_id=client.id))

    return render_template("developer/client_detail.html", form=form, client=client)
