from flask import request, render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.developer.base import developer_bp
from app.extensions import db
from app.models import Client


class NewClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])


@developer_bp.route("/new_client", methods=["GET", "POST"])
@login_required
def new_client():
    form = NewClientForm()

    if request.method == "POST":
        if form.validate():
            client = Client.create_new(form.name.data, current_user.id)
            db.session.commit()
            flash("Your app has been created", "success")

            return redirect(
                url_for("developer.handle_step", client_id=client.id, step="step-0")
            )

    return render_template("developer/new_client.html", form=form)
