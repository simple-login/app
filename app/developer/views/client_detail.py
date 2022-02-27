from io import BytesIO

from flask import request, render_template, redirect, url_for, flash
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import StringField, validators, TextAreaField

from app import s3
from app.config import ADMIN_EMAIL
from app.db import Session
from app.developer.base import developer_bp
from app.email_utils import send_email
from app.log import LOG
from app.models import Client, RedirectUri, File, Referral
from app.utils import random_string


class EditClientForm(FlaskForm):
    name = StringField("Name", validators=[validators.DataRequired()])
    url = StringField("Url", validators=[validators.DataRequired()])
    icon = FileField("Icon")


class ApprovalClientForm(FlaskForm):
    description = TextAreaField("Description", validators=[validators.DataRequired()])


# basic info
@developer_bp.route("/clients/<client_id>", methods=["GET", "POST"])
@login_required
def client_detail(client_id):
    form = EditClientForm()
    approval_form = ApprovalClientForm()

    is_new = "is_new" in request.args
    action = request.args.get("action")

    client = Client.get(client_id)
    if not client or client.user_id != current_user.id:
        flash("you cannot see this app", "warning")
        return redirect(url_for("developer.index"))

    # can't set value for a textarea field in jinja
    if request.method == "GET":
        approval_form.description.data = client.description

    if action == "edit" and form.validate_on_submit():
        client.name = form.name.data
        client.home_url = form.url.data

        if form.icon.data:
            # todo: remove current icon if any
            # todo: handle remove icon
            file_path = random_string(30)
            file = File.create(path=file_path, user_id=client.user_id)

            s3.upload_from_bytesio(file_path, BytesIO(form.icon.data.read()))

            Session.flush()
            LOG.d("upload file %s to s3", file)

            client.icon_id = file.id
            Session.flush()

        Session.commit()

        flash(f"{client.name} has been updated", "success")

        return redirect(url_for("developer.client_detail", client_id=client.id))

    if action == "submit" and approval_form.validate_on_submit():
        client.description = approval_form.description.data
        Session.commit()

        send_email(
            ADMIN_EMAIL,
            subject=f"{client.name} {client.id} submits for approval",
            plaintext="",
            html=f"""
            name: {client.name} <br>
            created: {client.created_at} <br>
            user: {current_user.email} <br>
            <br>
            {client.description}
            """,
        )

        flash(
            f"Thanks for submitting, we are informed and will come back to you asap!",
            "success",
        )

        return redirect(url_for("developer.client_detail", client_id=client.id))

    return render_template(
        "developer/client_details/basic_info.html",
        form=form,
        approval_form=approval_form,
        client=client,
        is_new=is_new,
    )


class OAuthSettingForm(FlaskForm):
    pass


@developer_bp.route("/clients/<client_id>/oauth_setting", methods=["GET", "POST"])
@login_required
def client_detail_oauth_setting(client_id):
    form = OAuthSettingForm()
    client = Client.get(client_id)
    if not client:
        flash("no such app", "warning")
        return redirect(url_for("developer.index"))

    if client.user_id != current_user.id:
        flash("you cannot see this app", "warning")
        return redirect(url_for("developer.index"))

    if form.validate_on_submit():
        uris = request.form.getlist("uri")

        # replace all uris. TODO: optimize this?
        for redirect_uri in client.redirect_uris:
            RedirectUri.delete(redirect_uri.id)

        for uri in uris:
            RedirectUri.create(client_id=client_id, uri=uri)

        Session.commit()

        flash(f"{client.name} has been updated", "success")

        return redirect(
            url_for("developer.client_detail_oauth_setting", client_id=client.id)
        )

    return render_template(
        "developer/client_details/oauth_setting.html", form=form, client=client
    )


@developer_bp.route("/clients/<client_id>/oauth_endpoint", methods=["GET", "POST"])
@login_required
def client_detail_oauth_endpoint(client_id):
    client = Client.get(client_id)
    if not client:
        flash("no such app", "warning")
        return redirect(url_for("developer.index"))

    if client.user_id != current_user.id:
        flash("you cannot see this app", "warning")
        return redirect(url_for("developer.index"))

    return render_template(
        "developer/client_details/oauth_endpoint.html", client=client
    )


class AdvancedForm(FlaskForm):
    pass


@developer_bp.route("/clients/<client_id>/advanced", methods=["GET", "POST"])
@login_required
def client_detail_advanced(client_id):
    form = AdvancedForm()
    client = Client.get(client_id)
    if not client:
        flash("no such app", "warning")
        return redirect(url_for("developer.index"))

    if client.user_id != current_user.id:
        flash("you cannot see this app", "warning")
        return redirect(url_for("developer.index"))

    if form.validate_on_submit():
        # delete client
        client_name = client.name
        Client.delete(client.id)
        Session.commit()
        LOG.d("Remove client %s", client)
        flash(f"{client_name} has been deleted", "success")

        return redirect(url_for("developer.index"))

    return render_template(
        "developer/client_details/advanced.html", form=form, client=client
    )


@developer_bp.route("/clients/<client_id>/referral", methods=["GET", "POST"])
@login_required
def client_detail_referral(client_id):
    client = Client.get(client_id)
    if not client:
        flash("no such app", "warning")
        return redirect(url_for("developer.index"))

    if client.user_id != current_user.id:
        flash("you cannot see this app", "warning")
        return redirect(url_for("developer.index"))

    if request.method == "POST":
        referral_id = request.form.get("referral-id")
        if not referral_id:
            flash("A referral must be selected", "error")
            return redirect(request.url)

        referral = Referral.get(referral_id)

        if not referral or referral.user_id != current_user.id:
            flash("something went wrong, refresh the page", "error")
            return redirect(request.url)

        client.referral_id = referral.id
        Session.commit()
        flash(f"Referral {referral.name} is now attached to {client.name}", "success")

    return render_template("developer/client_details/referral.html", client=client)
