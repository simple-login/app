from uuid import uuid4

from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from app.config import URL
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.email_utils import send_email, render
from app.extensions import limiter
from app.log import LOG
from app.models import (
    Alias,
    Contact,
    AliasUsedOn,
    AliasMailbox,
    User,
    ClientUser,
)
from app.models import Mailbox


def transfer(alias, new_user, new_mailboxes: [Mailbox]):
    # cannot transfer alias which is used for receiving newsletter
    if User.get_by(newsletter_alias_id=alias.id):
        raise Exception("Cannot transfer alias that's used to receive newsletter")

    # update user_id
    Session.query(Contact).filter(Contact.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    Session.query(AliasUsedOn).filter(AliasUsedOn.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    Session.query(ClientUser).filter(ClientUser.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    # remove existing mailboxes from the alias
    Session.query(AliasMailbox).filter(AliasMailbox.alias_id == alias.id).delete()

    # set mailboxes
    alias.mailbox_id = new_mailboxes.pop().id
    for mb in new_mailboxes:
        AliasMailbox.create(alias_id=alias.id, mailbox_id=mb.id)

    # alias has never been transferred before
    if not alias.original_owner_id:
        alias.original_owner_id = alias.user_id

    # inform previous owner
    old_user = alias.user
    send_email(
        old_user.email,
        f"Alias {alias.email} has been received",
        render(
            "transactional/alias-transferred.txt",
            alias=alias,
        ),
        render(
            "transactional/alias-transferred.html",
            alias=alias,
        ),
    )

    # now the alias belongs to the new user
    alias.user_id = new_user.id

    # set some fields back to default
    alias.disable_pgp = False
    alias.pinned = False

    Session.commit()


@dashboard_bp.route("/alias_transfer/send/<int:alias_id>/", methods=["GET", "POST"])
@login_required
def alias_transfer_send_route(alias_id):
    alias = Alias.get(alias_id)
    if not alias or alias.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if current_user.newsletter_alias_id == alias.id:
        flash(
            "This alias is currently used for receiving the newsletter and cannot be transferred",
            "error",
        )
        return redirect(url_for("dashboard.index"))

    if alias.transfer_token:
        alias_transfer_url = (
            URL + "/dashboard/alias_transfer/receive" + f"?token={alias.transfer_token}"
        )
    else:
        alias_transfer_url = None

    # generate a new transfer_token
    if request.method == "POST":
        if request.form.get("form-name") == "create":
            alias.transfer_token = str(uuid4())
            Session.commit()
            alias_transfer_url = (
                URL
                + "/dashboard/alias_transfer/receive"
                + f"?token={alias.transfer_token}"
            )
            flash("Share URL created", "success")
            return redirect(request.url)
        # request.form.get("form-name") == "remove"
        else:
            alias.transfer_token = None
            Session.commit()
            alias_transfer_url = None
            flash("Share URL deleted", "success")
            return redirect(request.url)

    return render_template(
        "dashboard/alias_transfer_send.html",
        alias=alias,
        alias_transfer_url=alias_transfer_url,
    )


@dashboard_bp.route("/alias_transfer/receive", methods=["GET", "POST"])
@limiter.limit("5/minute")
@login_required
def alias_transfer_receive_route():
    """
    URL has ?alias_id=signed_alias_id
    """
    token = request.args.get("token")
    alias = Alias.get_by(transfer_token=token)

    if not alias:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.index"))

    # alias already belongs to this user
    if alias.user_id == current_user.id:
        flash("You already own this alias", "warning")
        return redirect(url_for("dashboard.index"))

    # check if user has not exceeded the alias quota
    if not current_user.can_create_new_alias():
        LOG.d("%s can't receive new alias", current_user)
        flash(
            "You have reached free plan limit, please upgrade to create new aliases",
            "warning",
        )
        return redirect(url_for("dashboard.index"))

    mailboxes = current_user.mailboxes()

    if request.method == "POST":
        mailbox_ids = request.form.getlist("mailbox_ids")
        # check if mailbox is not tempered with
        mailboxes = []
        for mailbox_id in mailbox_ids:
            mailbox = Mailbox.get(mailbox_id)
            if (
                not mailbox
                or mailbox.user_id != current_user.id
                or not mailbox.verified
            ):
                flash("Something went wrong, please retry", "warning")
                return redirect(request.url)
            mailboxes.append(mailbox)

        if not mailboxes:
            flash("You must select at least 1 mailbox", "warning")
            return redirect(request.url)

        LOG.d(
            "transfer alias from %s to %s with %s", alias.user, current_user, mailboxes
        )
        transfer(alias, current_user, mailboxes)
        flash(f"You are now owner of {alias.email}", "success")
        return redirect(url_for("dashboard.index", highlight_alias_id=alias.id))

    return render_template(
        "dashboard/alias_transfer_receive.html",
        alias=alias,
        mailboxes=mailboxes,
    )
