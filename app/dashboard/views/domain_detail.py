import re

import arrow
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators, IntegerField

from app.config import EMAIL_SERVERS_WITH_PRIORITY, EMAIL_DOMAIN, JOB_DELETE_DOMAIN
from app.custom_domain_validation import CustomDomainValidation
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.dns_utils import (
    get_mx_domains,
    get_spf_domain,
    get_txt_record,
    is_mx_equivalent,
)
from app.log import LOG
from app.models import (
    CustomDomain,
    Alias,
    DomainDeletedAlias,
    Mailbox,
    DomainMailbox,
    AutoCreateRule,
    AutoCreateRuleMailbox,
    Job,
)
from app.regex_utils import regex_match
from app.utils import random_string, CSRFValidationForm


@dashboard_bp.route("/domains/<int:custom_domain_id>/dns", methods=["GET", "POST"])
@login_required
def domain_detail_dns(custom_domain_id):
    custom_domain: CustomDomain = CustomDomain.get(custom_domain_id)
    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    # generate a domain ownership txt token if needed
    if not custom_domain.ownership_verified and not custom_domain.ownership_txt_token:
        custom_domain.ownership_txt_token = random_string(30)
        Session.commit()

    spf_record = f"v=spf1 include:{EMAIL_DOMAIN} ~all"

    domain_validator = CustomDomainValidation(EMAIL_DOMAIN)
    csrf_form = CSRFValidationForm()

    dmarc_record = "v=DMARC1; p=quarantine; pct=100; adkim=s; aspf=s"

    mx_ok = spf_ok = dkim_ok = dmarc_ok = ownership_ok = True
    mx_errors = spf_errors = dkim_errors = dmarc_errors = ownership_errors = []

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "check-ownership":
            txt_records = get_txt_record(custom_domain.domain)

            if custom_domain.get_ownership_dns_txt_value() in txt_records:
                flash(
                    "Domain ownership is verified. Please proceed to the other records setup",
                    "success",
                )
                custom_domain.ownership_verified = True
                Session.commit()
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns",
                        custom_domain_id=custom_domain.id,
                        _anchor="dns-setup",
                    )
                )
            else:
                flash("We can't find the needed TXT record", "error")
                ownership_ok = False
                ownership_errors = txt_records

        elif request.form.get("form-name") == "check-mx":
            mx_domains = get_mx_domains(custom_domain.domain)

            if not is_mx_equivalent(mx_domains, EMAIL_SERVERS_WITH_PRIORITY):
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
                Session.commit()
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
        elif request.form.get("form-name") == "check-spf":
            spf_domains = get_spf_domain(custom_domain.domain)
            if EMAIL_DOMAIN in spf_domains:
                custom_domain.spf_verified = True
                Session.commit()
                flash("SPF is setup correctly", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                custom_domain.spf_verified = False
                Session.commit()
                flash(
                    f"SPF: {EMAIL_DOMAIN} is not included in your SPF record.",
                    "warning",
                )
                spf_ok = False
                spf_errors = get_txt_record(custom_domain.domain)

        elif request.form.get("form-name") == "check-dkim":
            dkim_errors = domain_validator.validate_dkim_records(custom_domain)
            if len(dkim_errors) == 0:
                flash("DKIM is setup correctly.", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                dkim_ok = False
                flash("DKIM: the CNAME record is not correctly set", "warning")

        elif request.form.get("form-name") == "check-dmarc":
            txt_records = get_txt_record("_dmarc." + custom_domain.domain)
            if dmarc_record in txt_records:
                custom_domain.dmarc_verified = True
                Session.commit()
                flash("DMARC is setup correctly", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                custom_domain.dmarc_verified = False
                Session.commit()
                flash(
                    "DMARC: The TXT record is not correctly set",
                    "warning",
                )
                dmarc_ok = False
                dmarc_errors = txt_records

    return render_template(
        "dashboard/domain_detail/dns.html",
        EMAIL_SERVERS_WITH_PRIORITY=EMAIL_SERVERS_WITH_PRIORITY,
        dkim_records=domain_validator.get_dkim_records(),
        **locals(),
    )


@dashboard_bp.route("/domains/<int:custom_domain_id>/info", methods=["GET", "POST"])
@login_required
def domain_detail(custom_domain_id):
    csrf_form = CSRFValidationForm()
    custom_domain: CustomDomain = CustomDomain.get(custom_domain_id)
    mailboxes = current_user.mailboxes()

    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "switch-catch-all":
            custom_domain.catch_all = not custom_domain.catch_all
            Session.commit()

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
                Session.commit()
                flash(
                    f"Default alias name for Domain {custom_domain.domain} has been set",
                    "success",
                )
            else:
                custom_domain.name = None
                Session.commit()
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
            Session.commit()

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
        elif request.form.get("form-name") == "update":
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
                    return redirect(
                        url_for(
                            "dashboard.domain_detail", custom_domain_id=custom_domain.id
                        )
                    )
                mailboxes.append(mailbox)

            if not mailboxes:
                flash("You must select at least 1 mailbox", "warning")
                return redirect(
                    url_for(
                        "dashboard.domain_detail", custom_domain_id=custom_domain.id
                    )
                )

            # first remove all existing domain-mailboxes links
            DomainMailbox.filter_by(domain_id=custom_domain.id).delete()
            Session.flush()

            for mailbox in mailboxes:
                DomainMailbox.create(domain_id=custom_domain.id, mailbox_id=mailbox.id)

            Session.commit()
            flash(f"{custom_domain.domain} mailboxes has been updated", "success")

            return redirect(
                url_for("dashboard.domain_detail", custom_domain_id=custom_domain.id)
            )

        elif request.form.get("form-name") == "delete":
            name = custom_domain.domain
            LOG.d("Schedule deleting %s", custom_domain)

            # Schedule delete domain job
            LOG.w("schedule delete domain job for %s", custom_domain)
            Job.create(
                name=JOB_DELETE_DOMAIN,
                payload={"custom_domain_id": custom_domain.id},
                run_at=arrow.now(),
                commit=True,
            )

            flash(
                f"{name} scheduled for deletion."
                f"You will receive a confirmation email when the deletion is finished",
                "success",
            )

            if custom_domain.is_sl_subdomain:
                return redirect(url_for("dashboard.subdomain_route"))
            else:
                return redirect(url_for("dashboard.custom_domain"))

    nb_alias = Alias.filter_by(custom_domain_id=custom_domain.id).count()

    return render_template("dashboard/domain_detail/info.html", **locals())


@dashboard_bp.route("/domains/<int:custom_domain_id>/trash", methods=["GET", "POST"])
@login_required
def domain_detail_trash(custom_domain_id):
    csrf_form = CSRFValidationForm()
    custom_domain = CustomDomain.get(custom_domain_id)
    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "empty-all":
            DomainDeletedAlias.filter_by(domain_id=custom_domain.id).delete()
            Session.commit()

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
            Session.commit()
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
        csrf_form=csrf_form,
    )


class AutoCreateRuleForm(FlaskForm):
    regex = StringField(
        "regex", validators=[validators.DataRequired(), validators.Length(max=128)]
    )

    order = IntegerField(
        "order",
        validators=[validators.DataRequired(), validators.NumberRange(min=0, max=100)],
    )


class AutoCreateTestForm(FlaskForm):
    local = StringField(
        "local part", validators=[validators.DataRequired(), validators.Length(max=128)]
    )


@dashboard_bp.route(
    "/domains/<int:custom_domain_id>/auto-create", methods=["GET", "POST"]
)
@login_required
def domain_detail_auto_create(custom_domain_id):
    custom_domain: CustomDomain = CustomDomain.get(custom_domain_id)
    mailboxes = current_user.mailboxes()
    new_auto_create_rule_form = AutoCreateRuleForm()

    auto_create_test_form = AutoCreateTestForm()
    auto_create_test_local, auto_create_test_result, auto_create_test_passed = (
        "",
        "",
        False,
    )

    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if request.form.get("form-name") == "create-auto-create-rule":
            if new_auto_create_rule_form.validate():
                # make sure order isn't used before
                for auto_create_rule in custom_domain.auto_create_rules:
                    auto_create_rule: AutoCreateRule
                    if auto_create_rule.order == int(
                        new_auto_create_rule_form.order.data
                    ):
                        flash(
                            "Another rule with the same order already exists", "error"
                        )
                        break
                else:
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
                            return redirect(
                                url_for(
                                    "dashboard.domain_detail_auto_create",
                                    custom_domain_id=custom_domain.id,
                                )
                            )
                        mailboxes.append(mailbox)

                    if not mailboxes:
                        flash("You must select at least 1 mailbox", "warning")
                        return redirect(
                            url_for(
                                "dashboard.domain_detail_auto_create",
                                custom_domain_id=custom_domain.id,
                            )
                        )

                    try:
                        re.compile(new_auto_create_rule_form.regex.data)
                    except Exception:
                        flash(
                            f"Invalid regex {new_auto_create_rule_form.regex.data}",
                            "error",
                        )
                        return redirect(
                            url_for(
                                "dashboard.domain_detail_auto_create",
                                custom_domain_id=custom_domain.id,
                            )
                        )

                    rule = AutoCreateRule.create(
                        custom_domain_id=custom_domain.id,
                        order=int(new_auto_create_rule_form.order.data),
                        regex=new_auto_create_rule_form.regex.data,
                        flush=True,
                    )

                    for mailbox in mailboxes:
                        AutoCreateRuleMailbox.create(
                            auto_create_rule_id=rule.id, mailbox_id=mailbox.id
                        )

                    Session.commit()

                    flash("New auto create rule has been created", "success")

                    return redirect(
                        url_for(
                            "dashboard.domain_detail_auto_create",
                            custom_domain_id=custom_domain.id,
                        )
                    )
        elif request.form.get("form-name") == "delete-auto-create-rule":
            rule_id = request.form.get("rule-id")
            rule: AutoCreateRule = AutoCreateRule.get(int(rule_id))

            if not rule or rule.custom_domain_id != custom_domain.id:
                flash("Something wrong, please retry", "error")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_auto_create",
                        custom_domain_id=custom_domain.id,
                    )
                )

            rule_order = rule.order
            AutoCreateRule.delete(rule_id)
            Session.commit()
            flash(f"Rule #{rule_order} has been deleted", "success")
            return redirect(
                url_for(
                    "dashboard.domain_detail_auto_create",
                    custom_domain_id=custom_domain.id,
                )
            )
        elif request.form.get("form-name") == "test-auto-create-rule":
            if auto_create_test_form.validate():
                local = auto_create_test_form.local.data
                auto_create_test_local = local

                for rule in custom_domain.auto_create_rules:
                    if regex_match(rule.regex, local):
                        auto_create_test_result = (
                            f"{local}@{custom_domain.domain} passes rule #{rule.order}"
                        )
                        auto_create_test_passed = True
                        break
                else:  # no rule passes
                    auto_create_test_result = (
                        f"{local}@{custom_domain.domain} doesn't pass any rule"
                    )

                return render_template(
                    "dashboard/domain_detail/auto-create.html", **locals()
                )

    return render_template("dashboard/domain_detail/auto-create.html", **locals())
