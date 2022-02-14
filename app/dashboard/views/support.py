import json
import urllib.parse
from typing import Union

import requests
from flask import render_template, request, flash, url_for, redirect, g
from flask_login import login_required, current_user
from werkzeug.datastructures import FileStorage

from app.config import ZENDESK_HOST, ZENDESK_API_TOKEN
from app.dashboard.base import dashboard_bp
from app.extensions import limiter
from app.log import LOG

VALID_MIME_TYPES = ["text/plain", "message/rfc822"]


def check_zendesk_response_status(response_code: int) -> bool:
    if response_code != 201:
        if response_code in (401, 422):
            LOG.error("Could not authenticate to Zendesk")
        else:
            LOG.error(
                "Problem with the Zendesk request. Status {}".format(response_code)
            )
        return False
    return True


def upload_file_to_zendesk_and_get_upload_token(
    email: str, file: FileStorage
) -> Union[None, str]:
    if file.mimetype not in VALID_MIME_TYPES and not file.mimetype.startswith("image/"):
        flash(
            "File {} is not an image, text or an email".format(file.filename), "warning"
        )
        return

    escaped_filename = urllib.parse.urlencode({"filename": file.filename})
    url = "https://{}/api/v2/uploads?{}".format(ZENDESK_HOST, escaped_filename)
    headers = {"content-type": file.mimetype}
    auth = ("{}/token".format(email), ZENDESK_API_TOKEN)
    response = requests.post(url, headers=headers, data=file.stream, auth=auth)
    if not check_zendesk_response_status(response.status_code):
        return

    data = response.json()
    return data["upload"]["token"]


def create_zendesk_request(email: str, content: str, files: [FileStorage]) -> bool:
    tokens = []
    for file in files:
        if not file.filename:
            continue
        token = upload_file_to_zendesk_and_get_upload_token(email, file)
        if token is None:
            return False
        tokens.append(token)

    data = {
        "request": {
            "subject": "Ticket created for user {}".format(current_user.id),
            "comment": {"type": "Comment", "body": content, "uploads": tokens},
            "requester": {
                "name": "SimpleLogin user {}".format(current_user.id),
                "email": email,
            },
        }
    }
    url = "https://{}/api/v2/requests.json".format(ZENDESK_HOST)
    headers = {"content-type": "application/json"}
    auth = (f"{email}/token", ZENDESK_API_TOKEN)
    response = requests.post(url, data=json.dumps(data), headers=headers, auth=auth)
    if not check_zendesk_response_status(response.status_code):
        return False

    return True


@dashboard_bp.route("/support", methods=["GET", "POST"])
@login_required
@limiter.limit(
    "2/hour",
    methods=["POST"],
    deduct_when=lambda r: hasattr(g, "deduct_limit") and g.deduct_limit,
)
def support_route():
    if not ZENDESK_HOST:
        flash("Support isn't enabled", "error")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        content = request.form.get("ticket_content")
        email = request.form.get("ticket_email")

        if not content:
            flash("Please add a description", "error")
            return render_template("dashboard/support.html", ticket_email=email)

        if not email:
            flash("Please provide an email address", "error")
            return render_template("dashboard/support.html", ticket_content=content)

        if not create_zendesk_request(
            email, content, request.files.getlist("ticket_files")
        ):
            flash(
                "Cannot create a Zendesk ticket, sorry for the inconvenience! Please retry later.",
                "error",
            )
            return render_template(
                "dashboard/support.html", ticket_email=email, ticket_content=content
            )

        # only enable rate limiting for successful Zendesk ticket creation
        g.deduct_limit = True
        flash(
            "Support ticket is created. You will receive an email about its status.",
            "success",
        )
        return redirect(url_for("dashboard.index"))

    return render_template("dashboard/support.html", ticket_email=current_user.email)
