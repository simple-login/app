from flask import render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.db import Session
from app.developer.base import developer_bp
from app.models import Client


class NewClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])
    url = StringField("Url", validators=[validators.DataRequired()])


@developer_bp.route("/new_client", methods=["GET", "POST"])
@login_required
def new_client():
    form = NewClientForm()

    if form.validate_on_submit():
        client = Client.create_new(form.name.data, current_user.id)
        client.home_url = form.url.data
        Session.commit()

        flash("Your website has been created", "success")

        return redirect(
            url_for("developer.client_detail", client_id=client.id, is_new=1)
        )

    return render_template("developer/new_client.html", form=form)
