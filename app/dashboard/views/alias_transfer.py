from flask import render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from itsdangerous import Signer

from app.config import ALIAS_TRANSFER_SECRET
from app.config import URL
from app.dashboard.base import dashboard_bp
from app.extensions import db
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
    db.session.query(Contact).filter(Contact.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    db.session.query(AliasUsedOn).filter(AliasUsedOn.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    db.session.query(ClientUser).filter(ClientUser.alias_id == alias.id).update(
        {"user_id": new_user.id}
    )

    # remove existing mailboxes from the alias
    db.session.query(AliasMailbox).filter(AliasMailbox.alias_id == alias.id).delete()

    # set mailboxes
    alias.mailbox_id = new_mailboxes.pop().id
    for mb in new_mailboxes:
        AliasMailbox.create(alias_id=alias.id, mailbox_id=mb.id)

    # alias has never been transferred before
    if not alias.original_owner_id:
        alias.original_owner_id = alias.user_id

    # now the alias belongs to the new user
    alias.user_id = new_user.id

    # set some fields back to default
    alias.disable_pgp = False
    alias.pinned = False

    db.session.commit()


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

    s = Signer(ALIAS_TRANSFER_SECRET)
    alias_id_signed = s.sign(str(alias.id)).decode()

    alias_transfer_url = (
        URL + "/dashboard/alias_transfer/receive" + f"?alias_id={alias_id_signed}"
    )

    return render_template(
        "dashboard/alias_transfer_send.html",
        alias=alias,
        alias_transfer_url=alias_transfer_url,
    )


@dashboard_bp.route("/alias_transfer/receive", methods=["GET", "POST"])
@login_required
def alias_transfer_receive_route():
    """
    URL has ?alias_id=signed_alias_id
    """
    s = Signer(ALIAS_TRANSFER_SECRET)
    signed_alias_id = request.args.get("alias_id")

    try:
        alias_id = int(s.unsign(signed_alias_id))
    except Exception:
        flash("Invalid link", "error")
        return redirect(url_for("dashboard.index"))
    else:
        alias = Alias.get(alias_id)

    # alias already belongs to this user
    if alias.user_id == current_user.id:
        flash("You already own this alias", "warning")
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
