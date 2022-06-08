from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.models import ApiKey


class NewApiKeyForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])


@dashboard_bp.route("/api_key", methods=["GET", "POST"])
@login_required
@sudo_required
def api_key():
    api_keys = (
        ApiKey.filter(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )

    new_api_key_form = NewApiKeyForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            api_key_id = request.form.get("api-key-id")

            api_key = ApiKey.get(api_key_id)

            if not api_key:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.api_key"))
            elif api_key.user_id != current_user.id:
                flash("You cannot delete this api key", "warning")
                return redirect(url_for("dashboard.api_key"))

            name = api_key.name
            ApiKey.delete(api_key_id)
            Session.commit()
            flash(f"API Key {name} has been deleted", "success")

        elif request.form.get("form-name") == "create":
            if new_api_key_form.validate():
                new_api_key = ApiKey.create(
                    name=new_api_key_form.name.data, user_id=current_user.id
                )
                Session.commit()
                flash(f"New API Key {new_api_key.name} has been created", "success")
                return render_template(
                    "dashboard/new_api_key.html", api_key=new_api_key
                )

        elif request.form.get("form-name") == "delete-all":
            ApiKey.delete_all(current_user.id)
            Session.commit()
            flash("All API Keys have been deleted", "success")

        return redirect(url_for("dashboard.api_key"))

    return render_template(
        "dashboard/api_key.html", api_keys=api_keys, new_api_key_form=new_api_key_form
    )
