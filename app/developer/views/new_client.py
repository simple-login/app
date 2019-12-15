from flask import render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import email_utils
from app.developer.base import developer_bp
from app.extensions import db
from app.log import LOG
from app.models import Client


class NewClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])


@developer_bp.route("/new_client", methods=["GET", "POST"])
@login_required
def new_client():
    form = NewClientForm()

    if form.validate_on_submit():
        client = Client.create_new(form.name.data, current_user.id)
        db.session.commit()

        flash("Your app has been created", "success")

        # if this is the first app user creates, sends an email to ask for feedback
        if db.session.query(Client).filter_by(user_id=current_user.id).count() == 1:
            LOG.d(f"send feedback email to user {current_user}")
            email_utils.send_new_app_email(current_user.email, current_user.name)

        return redirect(
            url_for("developer.client_detail", client_id=client.id, is_new=1)
        )

    return render_template("developer/new_client.html", form=form)
