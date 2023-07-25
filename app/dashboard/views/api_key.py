from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app import config
from app.dashboard.base import dashboard_bp
from app.dashboard.views.enter_sudo import sudo_required
from app.db import Session
from app.extensions import limiter
from app.models import ApiKey
from app.utils import CSRFValidationForm


class NewApiKeyForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])


def clean_up_unused_or_old_api_keys(user_id: int):
    total_keys = ApiKey.filter_by(user_id=user_id).count()
    if total_keys <= config.MAX_API_KEYS:
        return
    # Remove oldest unused
    for api_key in (
        ApiKey.filter_by(user_id=user_id, last_used=None)
        .order_by(ApiKey.created_at.asc())
        .all()
    ):
        Session.delete(api_key)
        total_keys -= 1
        if total_keys <= config.MAX_API_KEYS:
            return
    # Clean up oldest used
    for api_key in (
        ApiKey.filter_by(user_id=user_id).order_by(ApiKey.last_used.asc()).all()
    ):
        Session.delete(api_key)
        total_keys -= 1
        if total_keys <= config.MAX_API_KEYS:
            return


@dashboard_bp.route("/api_key", methods=["GET", "POST"])
@login_required
@sudo_required
@limiter.limit("10/hour")
def api_key():
    api_keys = (
        ApiKey.filter(ApiKey.user_id == current_user.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )

    csrf_form = CSRFValidationForm()
    new_api_key_form = NewApiKeyForm()

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
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
                clean_up_unused_or_old_api_keys(current_user.id)
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
        "dashboard/api_key.html",
        api_keys=api_keys,
        new_api_key_form=new_api_key_form,
        csrf_form=csrf_form,
    )
