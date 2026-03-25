import arrow

from app.models import CustomDomain
from tasks.check_custom_domains import check_all_custom_domains
from tests.utils import create_new_user, random_string


def test_check_custom_domain_deletes_old_domains():
    user = create_new_user()
    now = arrow.utcnow()
    cd_to_delete = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=False,
        created_at=now.shift(months=-3),
    ).id
    cd_to_keep = CustomDomain.create(
        user_id=user.id,
        domain=random_string(),
        verified=True,
        created_at=now.shift(months=-3),
    ).id
    check_all_custom_domains()
    assert CustomDomain.get(cd_to_delete) is None
    assert CustomDomain.get(cd_to_keep) is not None
