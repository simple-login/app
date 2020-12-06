from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators

from app.config import EMAIL_SERVERS_WITH_PRIORITY
from app.dashboard.base import dashboard_bp
from app.email_utils import get_email_domain_part
from app.extensions import db
from app.models import CustomDomain, Mailbox, DomainMailbox, SLDomain


class NewCustomDomainForm(FlaskForm):
    domain = StringField(
        "domain", validators=[validators.DataRequired(), validators.Length(max=128)]
    )


@dashboard_bp.route("/custom_domain", methods=["GET", "POST"])
@login_required
def custom_domain():
    custom_domains = CustomDomain.query.filter_by(user_id=current_user.id).all()
    mailboxes = current_user.mailboxes()
    new_custom_domain_form = NewCustomDomainForm()

    errors = {}

    if request.method == "POST":
        if request.form.get("form-name") == "create":
            if not current_user.is_premium():
                flash("Only premium plan can add custom domain", "warning")
                return redirect(url_for("dashboard.custom_domain"))

            if new_custom_domain_form.validate():
                new_domain = new_custom_domain_form.domain.data.lower().strip()

                if new_domain.startswith("http://"):
                    new_domain = new_domain[len("http://") :]

                if new_domain.startswith("https://"):
                    new_domain = new_domain[len("https://") :]

                if SLDomain.get_by(domain=new_domain):
                    flash("A custom domain cannot be a built-in domain.", "error")
                elif CustomDomain.get_by(domain=new_domain):
                    flash(f"{new_domain} already added", "warning")
                elif get_email_domain_part(current_user.email) == new_domain:
                    flash(
                        "You cannot add a domain that you are currently using for your personal email. "
                        "Please change your personal email to your real email",
                        "error",
                    )
                else:
                    new_custom_domain = CustomDomain.create(
                        domain=new_domain, user_id=current_user.id
                    )
                    db.session.commit()

                    mailbox_ids = request.form.getlist("mailbox_ids")
                    if mailbox_ids:
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
                                return redirect(url_for("dashboard.custom_domain"))
                            mailboxes.append(mailbox)

                        for mailbox in mailboxes:
                            DomainMailbox.create(
                                domain_id=new_custom_domain.id, mailbox_id=mailbox.id
                            )

                        db.session.commit()

                    flash(
                        f"New domain {new_custom_domain.domain} is created", "success"
                    )

                    return redirect(
                        url_for(
                            "dashboard.domain_detail_dns",
                            custom_domain_id=new_custom_domain.id,
                        )
                    )
        elif request.form.get("form-name") == "update":
            domain_id = request.form.get("domain-id")
            domain = CustomDomain.get(domain_id)

            if not domain or domain.user_id != current_user.id:
                flash("Unknown error. Refresh the page", "warning")
                return redirect(url_for("dashboard.custom_domain"))

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
                    return redirect(url_for("dashboard.custom_domain"))
                mailboxes.append(mailbox)

            if not mailboxes:
                flash("You must select at least 1 mailbox", "warning")
                return redirect(url_for("dashboard.custom_domain"))

            # first remove all existing domain-mailboxes links
            DomainMailbox.query.filter_by(domain_id=domain.id).delete()
            db.session.flush()

            for mailbox in mailboxes:
                DomainMailbox.create(domain_id=domain.id, mailbox_id=mailbox.id)

            db.session.commit()
            flash(f"Domain {domain.domain} has been updated", "success")

            return redirect(url_for("dashboard.custom_domain"))

    return render_template(
        "dashboard/custom_domain.html",
        custom_domains=custom_domains,
        new_custom_domain_form=new_custom_domain_form,
        EMAIL_SERVERS_WITH_PRIORITY=EMAIL_SERVERS_WITH_PRIORITY,
        errors=errors,
        mailboxes=mailboxes,
    )
