from __future__ import annotations

from flask import request
from flask_admin import expose

from app.admin.base import BaseAdminView
from app.email_utils import check_domain_for_mailbox, MailboxDomainCheckResult


class DomainCheckAdmin(BaseAdminView):
    @expose("/", methods=["GET"])
    def index(self):
        domain = request.args.get("domain", "").strip()
        result: MailboxDomainCheckResult | None = None

        if domain:
            result = check_domain_for_mailbox(domain)

        return self.render(
            "admin/domain_check.html",
            domain=domain,
            result=result,
        )
