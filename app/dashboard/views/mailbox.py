from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from itsdangerous import Signer, BadSignature
from wtforms import validators
from wtforms.fields.html5 import EmailField

from app.config import EMAIL_DOMAIN, ALIAS_DOMAINS, FLASK_SECRET, URL
from app.dashboard.base import dashboard_bp
from app.email_utils import (
    send_email,
    render,
    can_be_used_as_personal_email,
    email_already_used,
)
from app.extensions import db
from app.log import LOG
from app.models import Mailbox


class NewMailboxForm(FlaskForm):
    email = EmailField(
        "email", validators=[validators.DataRequired(), validators.Email()]
    )


@dashboard_bp.route("/mailbox", methods=["GET", "POST"])
@login_required
def mailbox_route():
    mailboxes = Mailbox.query.filter_by(user_id=current_user.id).all()

    new_mailbox_form = NewMailboxForm()

    if request.method == "POST":
        if request.form.get("form-name") == "delete":
            mailbox_id = request.form.get("mailbox-id")
            mailbox = Mailbox.get(mailbox_id)

            if not mailbox or mailbox.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            email = mailbox.email
            Mailbox.delete(mailbox_id)
            db.session.commit()
            flash(f"Mailbox {email} has been deleted", "success")

            return redirect(url_for("dashboard.mailbox_route"))

        elif request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add additional mailbox", "warning")
                return redirect(url_for("dashboard.mailbox_route"))

            if new_mailbox_form.validate():
                mailbox_email = new_mailbox_form.email.data.lower()

                if email_already_used(mailbox_email):
                    flash(f"{mailbox_email} already used", "error")
                elif not can_be_used_as_personal_email(mailbox_email):
                    flash(
                        f"You cannot use {mailbox_email}.", "error",
                    )
                else:
                    new_mailbox = Mailbox.create(
                        email=mailbox_email, user_id=current_user.id
                    )
                    db.session.commit()

                    s = Signer(FLASK_SECRET)
                    mailbox_id_signed = s.sign(str(new_mailbox.id)).decode()
                    verification_url = (
                        URL
                        + "/dashboard/mailbox_verify"
                        + f"?mailbox_id={mailbox_id_signed}"
                    )
                    send_email(
                        mailbox_email,
                        f"Please confirm your email {mailbox_email}",
                        render(
                            "transactional/verify-mailbox.txt",
                            user=current_user,
                            link=verification_url,
                            mailbox_email=mailbox_email,
                        ),
                        render(
                            "transactional/verify-mailbox.html",
                            user=current_user,
                            link=verification_url,
                            mailbox_email=mailbox_email,
                        ),
                    )

                    flash(
                        f"You are going to receive an email to confirm {mailbox_email}.",
                        "success",
                    )

                    return redirect(url_for("dashboard.mailbox_route"))

    return render_template(
        "dashboard/mailbox.html",
        mailboxes=mailboxes,
        new_mailbox_form=new_mailbox_form,
        EMAIL_DOMAIN=EMAIL_DOMAIN,
        ALIAS_DOMAINS=ALIAS_DOMAINS,
    )


@dashboard_bp.route("/mailbox_verify")
def mailbox_verify():
    s = Signer(FLASK_SECRET)
    mailbox_id = request.args.get("mailbox_id")

    try:
        r_id = int(s.unsign(mailbox_id))
    except BadSignature:
        flash("Invalid link. Please delete and re-add your mailbox", "error")
    else:
        mailbox = Mailbox.get(r_id)
        mailbox.verified = True
        db.session.commit()

        LOG.d("Mailbox %s is verified", mailbox)
        flash(
            f"The {mailbox.email} is now verified, you can start creating alias with it",
            "success",
        )
        return redirect(url_for("dashboard.mailbox_route"))
