import json

import requests
from flask import render_template, request, flash, url_for, redirect
from flask_login import login_required, current_user
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.log import LOG
from app.models import Alias, Mailbox


@dashboard_bp.route("/support", methods=["GET"])
@login_required
def show_support_dialog():
    return render_template( "dashboard/support.html" )


def createZendeskTicket(email: str, contents: str):
    data = {
        'request': {
            'subject': 'Ticket created for user {}'.format(current_user.id),
            'comment': {
                'type': 'Comment',
                'body': contents
            },
            'requester': {
                'name': "SimpleLogin user {}".format(current_user.id),
                'email': email
            }
        }
    }
    url = 'https://simplelogin.zendesk.com/api/v2/requests.json'
    headers = {'content-type': 'application/json'}
    r = requests.post(url, data=json.dumps(data), headers=headers)
    if r.status_code != 201:
        if r.status_code == 401 or 422:
            LOG.debug('Could not authenticate')
        else:
            LOG.debug('Problem with the request. Status ' + str(r.status_code))
    else:
        flash("Ticket was created. You should receive an email notification", "success")
        LOG.debug('Ticket created')


@dashboard_bp.route("/support", methods=["POST"])
@login_required
def process_support_dialog():
    contents = request.form.get("ticketContents") or ""
    email = request.form.get("ticketEmail") or ""
    if not contents:
        flash("Please add a description", "warning")
        return render_template("dashboard/support.html", ticketEmail=email)
    if not email:
        flash("Please add an email", "warning")
        return render_template("dashboard/support.html", ticketContents=contents)
    createZendeskTicket(email, contents)
    return redirect(url_for('dashboard.index'))
