from app.db import Session
from app.models import SLDomain, PartnerUser, AliasOptions
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
    assert [d.domain for d in domains] == user.available_sl_domains()
    # Free
    user.trial_end = None
    Session.flush()
    domains = user.get_sl_domains()
    assert len(domains) == 1
    assert domains[0].domain == "free_non_partner"
    assert [d.domain for d in domains] == user.available_sl_domains()


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
    assert [d.domain for d in domains] == user.available_sl_domains()
    # Show partner domains
    options = AliasOptions(
        show_sl_domains=True, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 2
    assert domains[0].domain == "free_partner"
    assert domains[1].domain == "free_non_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )
    # Only partner domains
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 1
    assert domains[0].domain == "free_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )


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
    assert [d.domain for d in domains] == user.available_sl_domains()
    # Show partner domains
    options = AliasOptions(
        show_sl_domains=True, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 4
    assert domains[0].domain == "premium_partner"
    assert domains[1].domain == "free_partner"
    assert domains[2].domain == "premium_non_partner"
    assert domains[3].domain == "free_non_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )
    # Only partner domains
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 2
    assert domains[0].domain == "premium_partner"
    assert domains[1].domain == "free_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )


def test_get_partner_and_free_default_domain():
    user = create_new_user()
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.default_alias_public_domain_id = (
        SLDomain.filter_by(partner_id=None, hidden=False).first().id
    )
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 3
    assert domains[0].domain == "premium_partner"
    assert domains[1].domain == "free_partner"
    assert domains[2].domain == "free_non_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )


def test_get_free_partner_and_premium_default_domain():
    user = create_new_user()
    user.trial_end = None
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.default_alias_public_domain_id = (
        SLDomain.filter_by(partner_id=None, hidden=False, premium_only=True).first().id
    )
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 1
    assert domains[0].domain == "free_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )


def test_get_free_partner_and_hidden_default_domain():
    user = create_new_user()
    user.trial_end = None
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.default_alias_public_domain_id = SLDomain.filter_by(hidden=True).first().id
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 1
    assert domains[0].domain == "free_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )


def test_get_free_partner_and_premium_partner():
    user = create_new_user()
    user.trial_end = None
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.default_alias_public_domain_id = (
        SLDomain.filter_by(hidden=False, premium_only=False).first().id
    )
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False,
        show_partner_domains=get_proton_partner(),
        show_partner_premium=True,
    )
    domains = user.get_sl_domains(alias_options=options)
    assert len(domains) == 3
    assert domains[0].domain == "premium_partner"
    assert domains[1].domain == "free_partner"
    assert domains[2].domain == "free_non_partner"
    assert [d.domain for d in domains] == user.available_sl_domains(
        alias_options=options
    )
