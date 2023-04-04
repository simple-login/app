from app.db import Session
from app.models import SLDomain, PartnerUser
from app.proton.utils import get_proton_partner
from init_app import add_sl_domains
from tests.utils import create_new_user, random_token


def setup_module():
    Session.query(SLDomain).delete()
    SLDomain.create(
        domain="hidden", premium_only=False, flush=True, order=5, hidden=True
    )
    SLDomain.create(domain="free_non_partner", premium_only=False, flush=True, order=4)
    SLDomain.create(
        domain="premium_non_partner", premium_only=True, flush=True, order=3
    )
    SLDomain.create(
        domain="free_partner",
        premium_only=False,
        flush=True,
        partner_id=get_proton_partner().id,
        order=2,
    )
    SLDomain.create(
        domain="premium_partner",
        premium_only=True,
        flush=True,
        partner_id=get_proton_partner().id,
        order=1,
    )
    Session.commit()


def teardown_module():
    Session.query(SLDomain).delete()
    add_sl_domains()


def test_get_non_partner_domains():
    user = create_new_user()
    domains = user.get_sl_domains()
    # Premium
    assert len(domains) == 2
    assert domains[0].domain == "premium_non_partner"
    assert domains[1].domain == "free_non_partner"
    # Free
    user.trial_end = None
    Session.flush()
    domains = user.get_sl_domains()
    assert len(domains) == 1
    assert domains[0].domain == "free_non_partner"


def test_get_free_with_partner_domains():
    user = create_new_user()
    user.trial_end = None
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    domains = user.get_sl_domains()
    # Default
    assert len(domains) == 1
    assert domains[0].domain == "free_non_partner"
    # Show partner domains
    domains = user.get_sl_domains(show_domains_for_partner=get_proton_partner())
    assert len(domains) == 2
    assert domains[0].domain == "free_partner"
    assert domains[1].domain == "free_non_partner"
    # Only partner domains
    domains = user.get_sl_domains(
        show_domains_for_partner=get_proton_partner(), show_sl_domains=False
    )
    assert len(domains) == 1
    assert domains[0].domain == "free_partner"


def test_get_premium_with_partner_domains():
    user = create_new_user()
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    domains = user.get_sl_domains()
    # Default
    assert len(domains) == 2
    assert domains[0].domain == "premium_non_partner"
    assert domains[1].domain == "free_non_partner"
    # Show partner domains
    domains = user.get_sl_domains(show_domains_for_partner=get_proton_partner())
    assert len(domains) == 4
    assert domains[0].domain == "premium_partner"
    assert domains[1].domain == "free_partner"
    assert domains[2].domain == "premium_non_partner"
    assert domains[3].domain == "free_non_partner"
    # Only partner domains
    domains = user.get_sl_domains(
        show_domains_for_partner=get_proton_partner(), show_sl_domains=False
    )
    assert len(domains) == 2
    assert domains[0].domain == "premium_partner"
    assert domains[1].domain == "free_partner"
