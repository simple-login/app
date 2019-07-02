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
from app.models import Client, File
from app.utils import random_string


class NewClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])
    icon = FileField("Icon")
    home_url = StringField("Home Url")


@developer_bp.route("/new_client", methods=["GET", "POST"])
@login_required
def new_client():
    form = NewClientForm()

    if request.method == "POST":
        if form.validate():
            client = Client.create_new(form.name.data, current_user.id)
            client.home_url = form.home_url.data
            db.session.commit()

            if form.icon.data:
                file_path = random_string(30)
                file = File.create(path=file_path)

                s3.upload_from_bytesio(file_path, BytesIO(form.icon.data.read()))

                db.session.commit()
                LOG.d("upload file %s to s3", file)

                client.icon_id = file.id
                db.session.commit()

            flash("New client has been created", "success")

            return redirect(url_for("developer.client_detail", client_id=client.id))

    return render_template("developer/new_client.html", form=form)
