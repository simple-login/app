from threading import Thread

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app.config import EMAIL_SERVERS_WITH_PRIORITY, EMAIL_DOMAIN
from app.dashboard.base import dashboard_bp
from app.dns_utils import (
    get_mx_domains,
    get_spf_domain,
    get_txt_record,
    get_cname_record,
)
from app.email_utils import send_email
from app.extensions import db
from app.log import LOG
from app.models import CustomDomain, Alias, DomainDeletedAlias


@dashboard_bp.route("/domains/<int:custom_domain_id>/dns", methods=["GET", "POST"])
@login_required
def domain_detail_dns(custom_domain_id):
    custom_domain = CustomDomain.get(custom_domain_id)
    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    spf_record = f"v=spf1 include:{EMAIL_DOMAIN} -all"

    # hardcode the DKIM selector here
    dkim_cname = f"dkim._domainkey.{EMAIL_DOMAIN}"

    dmarc_record = "v=DMARC1; p=quarantine; pct=100; adkim=s; aspf=s"

    mx_ok = spf_ok = dkim_ok = dmarc_ok = True
    mx_errors = spf_errors = dkim_errors = dmarc_errors = []

    if request.method == "POST":
        if request.form.get("form-name") == "check-mx":
            mx_domains = get_mx_domains(custom_domain.domain)

            if sorted(mx_domains) != sorted(EMAIL_SERVERS_WITH_PRIORITY):
                flash("The MX record is not correctly set", "warning")

                mx_ok = False
                # build mx_errors to show to user
                mx_errors = [
                    f"{priority} {domain}" for (priority, domain) in mx_domains
                ]
            else:
                flash(
                    "Your domain can start receiving emails. You can now use it to create alias",
                    "success",
                )
                custom_domain.verified = True
                db.session.commit()
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
        elif request.form.get("form-name") == "check-spf":
            spf_domains = get_spf_domain(custom_domain.domain)
            if EMAIL_DOMAIN in spf_domains:
                custom_domain.spf_verified = True
                db.session.commit()
                flash("SPF is setup correctly", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                custom_domain.spf_verified = False
                db.session.commit()
                flash(
                    f"SPF: {EMAIL_DOMAIN} is not included in your SPF record.",
                    "warning",
                )
                spf_ok = False
                spf_errors = get_txt_record(custom_domain.domain)

        elif request.form.get("form-name") == "check-dkim":
            dkim_record = get_cname_record("dkim._domainkey." + custom_domain.domain)
            if dkim_record == dkim_cname:
                flash("DKIM is setup correctly.", "success")
                custom_domain.dkim_verified = True
                db.session.commit()

                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                custom_domain.dkim_verified = False
                db.session.commit()
                flash("DKIM: the CNAME record is not correctly set", "warning")
                dkim_ok = False
                dkim_errors = [dkim_record or "[Empty]"]

        elif request.form.get("form-name") == "check-dmarc":
            txt_records = get_txt_record("_dmarc." + custom_domain.domain)
            if dmarc_record in txt_records:
                custom_domain.dmarc_verified = True
                db.session.commit()
                flash("DMARC is setup correctly", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                custom_domain.dmarc_verified = False
                db.session.commit()
                flash(
                    "DMARC: The TXT record is not correctly set",
                    "warning",
                )
                dmarc_ok = False
                dmarc_errors = txt_records

    return render_template(
        "dashboard/domain_detail/dns.html",
        EMAIL_SERVERS_WITH_PRIORITY=EMAIL_SERVERS_WITH_PRIORITY,
        **locals(),
    )


@dashboard_bp.route("/domains/<int:custom_domain_id>/info", methods=["GET", "POST"])
@login_required
def domain_detail(custom_domain_id):
    custom_domain = CustomDomain.get(custom_domain_id)
    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if request.form.get("form-name") == "switch-catch-all":
            custom_domain.catch_all = not custom_domain.catch_all
            db.session.commit()

            if custom_domain.catch_all:
                flash(
                    f"The catch-all has been enabled for {custom_domain.domain}",
                    "success",
                )
            else:
                flash(
                    f"The catch-all has been disabled for {custom_domain.domain}",
                    "warning",
                )
            return redirect(
                url_for("dashboard.domain_detail", custom_domain_id=custom_domain.id)
            )
        elif request.form.get("form-name") == "set-name":
            if request.form.get("action") == "save":
                custom_domain.name = request.form.get("alias-name").replace("\n", "")
                db.session.commit()
                flash(
                    f"Default alias name for Domain {custom_domain.domain} has been set",
                    "success",
                )
            else:
                custom_domain.name = None
                db.session.commit()
                flash(
                    f"Default alias name for Domain {custom_domain.domain} has been removed",
                    "info",
                )

            return redirect(
                url_for("dashboard.domain_detail", custom_domain_id=custom_domain.id)
            )
        elif request.form.get("form-name") == "switch-random-prefix-generation":
            custom_domain.random_prefix_generation = (
                not custom_domain.random_prefix_generation
            )
            db.session.commit()

            if custom_domain.random_prefix_generation:
                flash(
                    f"Random prefix generation has been enabled for {custom_domain.domain}",
                    "success",
                )
            else:
                flash(
                    f"Random prefix generation has been disabled for {custom_domain.domain}",
                    "warning",
                )
            return redirect(
                url_for("dashboard.domain_detail", custom_domain_id=custom_domain.id)
            )
        elif request.form.get("form-name") == "delete":
            name = custom_domain.domain
            LOG.d("Schedule deleting %s", custom_domain)
            Thread(target=delete_domain, args=(custom_domain_id,)).start()
            flash(
                f"{name} scheduled for deletion."
                f"You will receive a confirmation email when the deletion is finished",
                "success",
            )

            return redirect(url_for("dashboard.custom_domain"))

    nb_alias = Alias.filter_by(custom_domain_id=custom_domain.id).count()

    return render_template("dashboard/domain_detail/info.html", **locals())


def delete_domain(custom_domain_id: CustomDomain):
    from server import create_light_app

    with create_light_app().app_context():
        custom_domain = CustomDomain.get(custom_domain_id)
        if not custom_domain:
            return

        domain_name = custom_domain.domain
        user = custom_domain.user

        CustomDomain.delete(custom_domain.id)
        db.session.commit()

        LOG.d("Domain %s deleted", domain_name)

        send_email(
            user.email,
            f"Your domain {domain_name} has been deleted",
            f"""Domain {domain_name} along with its aliases are deleted successfully.

Regards,
SimpleLogin team.
        """,
        )


@dashboard_bp.route("/domains/<int:custom_domain_id>/trash", methods=["GET", "POST"])
@login_required
def domain_detail_trash(custom_domain_id):
    custom_domain = CustomDomain.get(custom_domain_id)
    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if request.form.get("form-name") == "empty-all":
            DomainDeletedAlias.filter_by(domain_id=custom_domain.id).delete()
            db.session.commit()

            flash("All deleted aliases can now be re-created", "success")
            return redirect(
                url_for(
                    "dashboard.domain_detail_trash", custom_domain_id=custom_domain.id
                )
            )
        elif request.form.get("form-name") == "remove-single":
            deleted_alias_id = request.form.get("deleted-alias-id")
            deleted_alias = DomainDeletedAlias.get(deleted_alias_id)
            if not deleted_alias or deleted_alias.domain_id != custom_domain.id:
                flash("Unknown error, refresh the page", "warning")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_trash",
                        custom_domain_id=custom_domain.id,
                    )
                )

            DomainDeletedAlias.delete(deleted_alias.id)
            db.session.commit()
            flash(
                f"{deleted_alias.email} can now be re-created",
                "success",
            )

            return redirect(
                url_for(
                    "dashboard.domain_detail_trash", custom_domain_id=custom_domain.id
                )
            )

    domain_deleted_aliases = DomainDeletedAlias.filter_by(
        domain_id=custom_domain.id
    ).all()

    return render_template(
        "dashboard/domain_detail/trash.html",
        domain_deleted_aliases=domain_deleted_aliases,
        custom_domain=custom_domain,
    )
