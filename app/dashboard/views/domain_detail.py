import re

from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, validators, IntegerField

from app import config
from app.constants import DMARC_RECORD
from app.custom_domain_utils import delete_custom_domain, set_custom_domain_mailboxes
from app.custom_domain_validation import CustomDomainValidation
from app.dashboard.base import dashboard_bp
from app.db import Session
from app.models import (
    CustomDomain,
    Alias,
    DomainDeletedAlias,
    Mailbox,
    AutoCreateRule,
    AutoCreateRuleMailbox,
)
from app.regex_utils import regex_match
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction
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

    domain_validator = CustomDomainValidation(
        dkim_domain=config.EMAIL_DOMAIN,
        partner_domains=config.PARTNER_DNS_CUSTOM_DOMAINS,
        partner_domains_validation_prefixes=config.PARTNER_CUSTOM_DOMAIN_VALIDATION_PREFIXES,
    )
    csrf_form = CSRFValidationForm()

    mx_ok = spf_ok = dkim_ok = dmarc_ok = ownership_ok = True
    mx_errors = spf_errors = dkim_errors = dmarc_errors = ownership_errors = []

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "check-ownership":
            ownership_validation_result = domain_validator.validate_domain_ownership(
                custom_domain
            )
            if ownership_validation_result.success:
                flash(
                    "Domain ownership is verified. Please proceed to the other records setup",
                    "success",
                )
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
                ownership_errors = ownership_validation_result.errors

        elif request.form.get("form-name") == "check-mx":
            mx_validation_result = domain_validator.validate_mx_records(custom_domain)
            if mx_validation_result.success:
                flash(
                    "Your domain can start receiving emails. You can now use it to create alias",
                    "success",
                )
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                flash("The MX record is not correctly set", "warning")
                mx_ok = False
                mx_errors = mx_validation_result.errors

        elif request.form.get("form-name") == "check-spf":
            spf_validation_result = domain_validator.validate_spf_records(custom_domain)
            if spf_validation_result.success:
                flash("SPF is setup correctly", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                flash(
                    f"SPF: {config.EMAIL_DOMAIN} is not included in your SPF record.",
                    "warning",
                )
                spf_ok = False
                spf_errors = spf_validation_result.errors

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
            dmarc_validation_result = domain_validator.validate_dmarc_records(
                custom_domain
            )
            if dmarc_validation_result.success:
                flash("DMARC is setup correctly", "success")
                return redirect(
                    url_for(
                        "dashboard.domain_detail_dns", custom_domain_id=custom_domain.id
                    )
                )
            else:
                flash(
                    "DMARC: The TXT record is not correctly set",
                    "warning",
                )
                dmarc_ok = False
                dmarc_errors = dmarc_validation_result.errors

    return render_template(
        "dashboard/domain_detail/dns.html",
        EMAIL_SERVERS_WITH_PRIORITY=config.EMAIL_SERVERS_WITH_PRIORITY,
        ownership_records=domain_validator.get_ownership_verification_record(
            custom_domain
        ),
        expected_mx_records=domain_validator.get_expected_mx_records(custom_domain),
        dkim_records=domain_validator.get_dkim_records(custom_domain),
        spf_record=domain_validator.get_expected_spf_record(custom_domain),
        dmarc_record=DMARC_RECORD,
        **locals(),
    )


@dashboard_bp.route("/domains/<int:custom_domain_id>/info", methods=["GET", "POST"])
@login_required
def domain_detail(custom_domain_id):
    csrf_form = CSRFValidationForm()
    custom_domain: CustomDomain = CustomDomain.get(custom_domain_id)
    mailboxes = [mb for mb in current_user.mailboxes() if not mb.is_admin_disabled()]

    if not custom_domain or custom_domain.user_id != current_user.id:
        flash("You cannot see this page", "warning")
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        if not csrf_form.validate():
            flash("Invalid request", "warning")
            return redirect(request.url)
        if request.form.get("form-name") == "switch-catch-all":
            custom_domain.catch_all = not custom_domain.catch_all
            emit_user_audit_log(
                user=current_user,
                action=UserAuditLogAction.UpdateCustomDomain,
                message=f"Switched custom domain {custom_domain.id} ({custom_domain.domain}) catch all to {custom_domain.catch_all}",
            )
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
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateCustomDomain,
                    message=f"Switched custom domain {custom_domain.id} ({custom_domain.domain}) name",
                )
                Session.commit()
                flash(
                    f"Default alias name for Domain {custom_domain.domain} has been set",
                    "success",
                )
            else:
                custom_domain.name = None
                emit_user_audit_log(
                    user=current_user,
                    action=UserAuditLogAction.UpdateCustomDomain,
                    message=f"Cleared custom domain {custom_domain.id} ({custom_domain.domain}) name",
                )
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
            emit_user_audit_log(
                user=current_user,
                action=UserAuditLogAction.UpdateCustomDomain,
                message=f"Switched custom domain {custom_domain.id} ({custom_domain.domain}) random prefix generation to {custom_domain.random_prefix_generation}",
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
            result = set_custom_domain_mailboxes(
                user_id=current_user.id,
                custom_domain=custom_domain,
                mailbox_ids=mailbox_ids,
            )

            if result.success:
                flash(f"{custom_domain.domain} mailboxes has been updated", "success")
            else:
                flash(result.reason.value, "warning")

            return redirect(
                url_for("dashboard.domain_detail", custom_domain_id=custom_domain.id)
            )

        elif request.form.get("form-name") == "delete":
            name = custom_domain.domain

            delete_custom_domain(custom_domain)

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

    display_name = StringField(
        "display name", validators=[validators.Optional(), validators.Length(max=128)]
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
    mailboxes = [mb for mb in current_user.mailboxes() if not mb.is_admin_disabled()]
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
                        if mailbox.is_admin_disabled():
                            flash(
                                "Cannot assign admin-disabled mailbox. Please contact support.",
                                "error",
                            )
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

                    display_name = None
                    if new_auto_create_rule_form.display_name.data:
                        raw_display = new_auto_create_rule_form.display_name.data
                        display_name = (
                            raw_display.replace("\r", " ").replace("\n", " ").strip()
                        )

                    rule = AutoCreateRule.create(
                        custom_domain_id=custom_domain.id,
                        order=int(new_auto_create_rule_form.order.data),
                        regex=new_auto_create_rule_form.regex.data,
                        display_name=display_name or None,
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
