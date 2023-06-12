import re

from app.alias_suffix import get_alias_suffixes
from app.db import Session
from app.models import SLDomain, PartnerUser, AliasOptions, CustomDomain
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


def test_get_default_domain_even_if_is_not_allowed():
    user = create_new_user()
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.trial_end = None
    default_domain = SLDomain.filter_by(
        hidden=False, partner_id=None, premium_only=False
    ).first()
    user.default_alias_public_domain_id = default_domain.id
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    suffixes = get_alias_suffixes(user, alias_options=options)
    assert suffixes[0].domain == default_domain.domain


def test_get_default_domain_hidden():
    user = create_new_user()
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.trial_end = None
    default_domain = SLDomain.filter_by(
        hidden=True, partner_id=None, premium_only=False
    ).first()
    user.default_alias_public_domain_id = default_domain.id
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    suffixes = get_alias_suffixes(user, alias_options=options)
    for suffix in suffixes:
        domain = SLDomain.get_by(domain=suffix.domain)
        assert not domain.hidden
    assert suffixes[0].domain != default_domain.domain


def test_get_default_domain_is_premium_for_free_user():
    user = create_new_user()
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    user.trial_end = None
    default_domain = SLDomain.filter_by(partner_id=None, premium_only=True).first()
    user.default_alias_public_domain_id = default_domain.id
    Session.flush()
    options = AliasOptions(
        show_sl_domains=False, show_partner_domains=get_proton_partner()
    )
    suffixes = get_alias_suffixes(user, alias_options=options)
    for suffix in suffixes:
        domain = SLDomain.get_by(domain=suffix.domain)
        assert not domain.premium_only
    assert suffixes[0].domain != default_domain.domain


def test_suffixes_are_valid():
    user = create_new_user()
    PartnerUser.create(
        partner_id=get_proton_partner().id,
        user_id=user.id,
        external_user_id=random_token(10),
        flush=True,
    )
    CustomDomain.create(
        user_id=user.id, domain=f"{random_token(10)}.com", verified=True
    )
    user.trial_end = None
    Session.flush()
    options = AliasOptions(
        show_sl_domains=True, show_partner_domains=get_proton_partner()
    )
    alias_suffixes = get_alias_suffixes(user, alias_options=options)
    valid_re = re.compile(r"^(\.[\w_]+)?@[\.\w]+$")
    has_prefix = 0
    for suffix in alias_suffixes:
        match = valid_re.match(suffix.suffix)
        assert match is not None
        if len(match.groups()) >= 1:
            has_prefix += 1
    assert has_prefix > 0


def test_get_default_domain_is_only_shown_once():
    user = create_new_user()
    default_domain = SLDomain.filter_by(hidden=False).order_by(SLDomain.order).first()
    user.default_alias_public_domain_id = default_domain.id
    Session.flush()
    options = AliasOptions(
        show_sl_domains=True, show_partner_domains=get_proton_partner()
    )
    suffixes = get_alias_suffixes(user, alias_options=options)
    found_default = False
    found_domains = set()
    for suffix in suffixes:
        assert suffix.domain not in found_domains
        found_domains.add(suffix.domain)
        if default_domain.domain == suffix.domain:
            found_default = True
    assert found_default
