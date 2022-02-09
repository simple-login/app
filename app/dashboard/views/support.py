import json
import urllib.parse
from typing import Union

import requests
from flask import render_template, request, flash, url_for, redirect
from flask_login import login_required, current_user
from werkzeug.datastructures import FileStorage

from app.dashboard.base import dashboard_bp
from app.log import LOG
from app.models import Mailbox
from app.config import ZENDESK_HOST

VALID_MIME_TYPES = ['text/plain', 'message/rfc822']


@dashboard_bp.route("/support", methods=["GET"])
@login_required
def show_support_dialog():
    if not ZENDESK_HOST:
        return render_template("dashboard/support_disabled.html")
    return render_template("dashboard/support.html", ticketEmail=current_user.email)


def check_zendesk_response_status(response_code: int) -> bool:
    if response_code != 201:
        if response_code in (401 or 422):
            LOG.debug('Could not authenticate')
        else:
            LOG.debug('Problem with the request. Status {}'.format(response_code))
        return False
    return True


def upload_file_to_zendesk(file: FileStorage) -> Union[None, str]:
    if file.mimetype not in VALID_MIME_TYPES and not file.mimetype.startswith('image/'):
        flash('File {} is not an image, text or an email'.format(file.filename), "warning")
        return
    escaped_filename = urllib.parse.urlencode({'filename': file.filename})
    url = 'https://{}/api/v2/uploads?{}'.format(ZENDESK_HOST, escaped_filename)
    headers = {'content-type': file.mimetype}
    response = requests.post(url, headers=headers, data=file.stream)
    if not check_zendesk_response_status(response.status_code):
        return
    data = response.json()
    return data['upload']['token']


def create_zendesk_request(email: str, contents: str, files: [FileStorage]) -> bool:
    tokens = []
    for file in files:
        token = upload_file_to_zendesk(file)
        if token is None:
            return False
        tokens.append(token)
    data = {
        'request': {
            'subject': 'Ticket created for user {}'.format(current_user.id),
            'comment': {
                'type': 'Comment',
                'body': contents,
                'uploads': tokens
            },
            'requester': {
                'name': "SimpleLogin user {}".format(current_user.id),
                'email': email
            }
        }
    }
    url = 'https://{}/api/v2/requests.json'.format(ZENDESK_HOST)
    headers = {'content-type': 'application/json'}
    response = requests.post(url, data=json.dumps(data), headers=headers)
    if not check_zendesk_response_status(response.status_code):
        return False
    flash("Ticket was created. You should receive an email notification", "success")
    LOG.debug('Ticket created')
    return True


@dashboard_bp.route("/support", methods=["POST"])
@login_required
def process_support_dialog():
    if not ZENDESK_HOST:
        return render_template("dashboard/support_disabled.html")
    contents = request.form.get("ticketContents") or ""
    email = request.form.get("ticketEmail") or ""
    if not contents:
        flash("Please add a description", "warning")
        return render_template("dashboard/support.html", ticketEmail=email)
    if not email:
        flash("Please add an email", "warning")
        return render_template("dashboard/support.html", ticketContents=contents)
    if create_zendesk_request(email, contents, request.files.getlist('ticketFiles')):
        return render_template("dashboard/support_ticket_created.html", ticketEmail=email)
    return render_template("dashboard/support.html", ticketEmail=email, ticketContents=contents)
