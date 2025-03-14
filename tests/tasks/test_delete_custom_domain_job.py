from typing import List

from app.alias_audit_log_utils import AliasAuditLogAction
from app.alias_delete import move_alias_to_trash
from app.db import Session
from app.models import CustomDomain, Alias, User, AliasAuditLog
from tasks.delete_custom_domain_job import DeleteCustomDomainJob
from tests.utils import create_new_user, random_domain, random_email


def alias_for_domain(user: User, domain: CustomDomain, trashed: bool = False) -> Alias:
    alias = Alias.create(
        user_id=user.id,
        email=random_email(),
        mailbox_id=user.default_mailbox_id,
        custom_domain_id=domain.id,
    )
    if trashed:
        move_alias_to_trash(alias, user)
    Session.commit()
    return alias


def assert_alias_audit_log(
    alias_id: int, expected_length: int, expected_last_action: AliasAuditLogAction
):
    audit_logs: List[AliasAuditLog] = AliasAuditLog.filter_by(alias_id=alias_id).all()
    assert len(audit_logs) == expected_length
    assert audit_logs[expected_length - 1].action == expected_last_action.value


def test_delete_custom_domain_removes_aliases():
    user = create_new_user()

    cd = CustomDomain.create(user_id=user.id, domain=random_domain())
    a1 = alias_for_domain(user, cd)
    a2 = alias_for_domain(user, cd, True)

    a1_id = a1.id
    a2_id = a2.id

    job = DeleteCustomDomainJob(cd)
    job.run()

    assert_alias_audit_log(a1_id, 2, AliasAuditLogAction.DeleteAlias)
    assert_alias_audit_log(a2_id, 3, AliasAuditLogAction.DeleteAlias)
