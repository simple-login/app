from typing import Optional

from app.db import Session
from app.email_utils import send_email
from app.log import LOG
from app.models import Job, CustomDomain
from app.user_audit_log_utils import emit_user_audit_log, UserAuditLogAction


class DeleteCustomDomainJob:
    def __init__(self, custom_domain: CustomDomain):
        self.custom_domain = custom_domain

    @staticmethod
    def create_from_job(job: Job) -> Optional["DeleteCustomDomainJob"]:
        custom_domain_id = job.payload.get("custom_domain_id")
        if not custom_domain_id:
            LOG.error(
                f"Job {job.id} did not have custom_domain_id property. Payload: {job.payload}"
            )
            return None
        custom_domain: Optional[CustomDomain] = CustomDomain.get(custom_domain_id)
        if not custom_domain:
            LOG.error(f"Could not find CustomDomain: {custom_domain_id}")
            return None

        return DeleteCustomDomainJob(custom_domain)

    def run(self):
        custom_domain_id = self.custom_domain.id
        is_subdomain = self.custom_domain.is_sl_subdomain
        domain_name = self.custom_domain.domain
        user = self.custom_domain.user

        custom_domain_partner_id = self.custom_domain.partner_id
        CustomDomain.delete(self.custom_domain.id)
        Session.commit()

        if is_subdomain:
            message = f"Delete subdomain {custom_domain_id} ({domain_name})"
        else:
            message = f"Delete custom domain {custom_domain_id} ({domain_name})"
        emit_user_audit_log(
            user=user,
            action=UserAuditLogAction.DeleteCustomDomain,
            message=message,
            commit=True,
        )

        LOG.d("Domain %s deleted", domain_name)

        if custom_domain_partner_id is None and user.can_send_or_receive():
            send_email(
                user.email,
                f"Your domain {domain_name} has been deleted",
                f"""Domain {domain_name} along with its aliases are deleted successfully.

        Regards,
        SimpleLogin team.
        """,
                retries=3,
            )
