from app.models import UserAuditLog
from app.payments.coinbase import create_coinbase_subscription
from app.user_audit_log_utils import UserAuditLogAction
from tests.utils import create_new_user, random_token


def test_create_coinbase_subscription():
    user = create_new_user()
    code = random_token()
    sub = create_coinbase_subscription(user, code)
    assert sub.code == code
    audit_log = (
        UserAuditLog.filter_by(user_id=user.id).order_by(UserAuditLog.id.desc()).first()
    )
    assert audit_log.action == UserAuditLogAction.Upgrade.value


def test_extend_coinbase_subscription():
    user = create_new_user()
    code1 = random_token()
    create_coinbase_subscription(user, code1)
    code2 = random_token()
    sub = create_coinbase_subscription(user, code2)
    assert sub.code == code2
    audit_log = (
        UserAuditLog.filter_by(user_id=user.id).order_by(UserAuditLog.id.desc()).first()
    )
    assert audit_log.action == UserAuditLogAction.SubscriptionExtended.value
