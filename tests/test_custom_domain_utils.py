from typing import Optional

from app import config
from app.alias_delete import move_alias_to_trash
from app.config import ALIAS_DOMAINS
from app.custom_domain_utils import (
    can_domain_be_used,
    create_custom_domain,
    is_valid_domain,
    sanitize_domain,
    set_custom_domain_mailboxes,
    CannotUseDomainReason,
    CannotSetCustomDomainMailboxesCause,
    count_custom_domain_aliases,
)
from app.db import Session
from app.models import User, CustomDomain, Mailbox, DomainMailbox, Alias
from tests.utils import create_new_user, random_string, random_domain
from tests.utils import get_proton_partner, random_email

user: Optional[User] = None


def setup_module():
    global user
    config.SKIP_MX_LOOKUP_ON_CHECK = True
    user = create_new_user()
    user.trial_end = None
    user.lifetime = True
    Session.commit()


# is_valid_domain
def test_is_valid_domain():
    assert is_valid_domain("example.com") is True
    assert is_valid_domain("sub.example.com") is True
    assert is_valid_domain("ex-ample.com") is True

    assert is_valid_domain("-example.com") is False
    assert is_valid_domain("example-.com") is False
    assert is_valid_domain("exa_mple.com") is False
    assert is_valid_domain("example..com") is False
    assert is_valid_domain("") is False
    assert is_valid_domain("a" * 64 + ".com") is False
    assert is_valid_domain("a" * 63 + ".com") is True
    assert is_valid_domain("example.com.") is True
    assert is_valid_domain(".example.com") is False
    assert is_valid_domain("example..com") is False
    assert is_valid_domain("example.com-") is False


# can_domain_be_used
def test_can_domain_be_used():
    domain = f"{random_string(10)}.com"
    res = can_domain_be_used(user, domain)
    assert res is None


def test_can_domain_be_used_existing_domain():
    domain = random_domain()
    CustomDomain.create(user_id=user.id, domain=domain, commit=True)
    res = can_domain_be_used(user, domain)
    assert res is CannotUseDomainReason.DomainAlreadyUsed


def test_can_domain_be_used_sl_domain():
    domain = ALIAS_DOMAINS[0]
    res = can_domain_be_used(user, domain)
    assert res is CannotUseDomainReason.BuiltinDomain


def test_can_domain_be_used_domain_of_user_email():
    domain = user.email.split("@")[1]
    res = can_domain_be_used(user, domain)
    assert res is CannotUseDomainReason.DomainPartOfUserEmail


def test_can_domain_be_used_domain_of_existing_mailbox():
    domain = random_domain()
    Mailbox.create(user_id=user.id, email=f"email@{domain}", verified=True, commit=True)
    res = can_domain_be_used(user, domain)
    assert res is CannotUseDomainReason.DomainUserInMailbox


def test_can_domain_be_used_invalid_domain():
    domain = f"{random_string(10)}@lol.com"
    res = can_domain_be_used(user, domain)
    assert res is CannotUseDomainReason.InvalidDomain


# sanitize_domain
def test_can_sanitize_domain_empty():
    assert sanitize_domain("") == ""


def test_can_sanitize_domain_starting_with_http():
    domain = "test.domain"
    assert sanitize_domain(f"http://{domain}") == domain


def test_can_sanitize_domain_starting_with_https():
    domain = "test.domain"
    assert sanitize_domain(f"https://{domain}") == domain


def test_can_sanitize_domain_correct_domain():
    domain = "test.domain"
    assert sanitize_domain(domain) == domain


# create_custom_domain
def test_can_create_custom_domain():
    domain = random_domain()
    res = create_custom_domain(user=user, domain=domain)
    assert res.success is True
    assert res.redirect is None
    assert res.message == ""
    assert res.message_category == ""
    assert res.instance is not None

    assert res.instance.domain == domain
    assert res.instance.user_id == user.id


def test_can_create_custom_domain_validates_if_parent_is_validated():
    root_domain = random_domain()
    subdomain = f"{random_string(10)}.{root_domain}"

    # Create custom domain with the root domain
    CustomDomain.create(
        user_id=user.id,
        domain=root_domain,
        verified=True,
        ownership_verified=True,
        commit=True,
    )

    # Create custom domain with subdomain. Should automatically be verified
    res = create_custom_domain(user=user, domain=subdomain)
    assert res.success is True
    assert res.instance.domain == subdomain
    assert res.instance.user_id == user.id
    assert res.instance.ownership_verified is True


def test_creates_custom_domain_with_partner_id():
    domain = random_domain()
    proton_partner = get_proton_partner()
    res = create_custom_domain(user=user, domain=domain, partner_id=proton_partner.id)
    assert res.success is True
    assert res.instance.domain == domain
    assert res.instance.user_id == user.id
    assert res.instance.partner_id == proton_partner.id


# set_custom_domain_mailboxes
def test_set_custom_domain_mailboxes_empty_list():
    domain = CustomDomain.create(user_id=user.id, domain=random_domain(), commit=True)
    res = set_custom_domain_mailboxes(user.id, domain, [])
    assert res.success is False
    assert res.reason == CannotSetCustomDomainMailboxesCause.NoMailboxes


def test_set_custom_domain_mailboxes_mailbox_from_another_user():
    other_user = create_new_user()
    other_mailbox = Mailbox.create(
        user_id=other_user.id, email=random_email(), verified=True
    )
    domain = CustomDomain.create(user_id=user.id, domain=random_domain(), commit=True)

    res = set_custom_domain_mailboxes(user.id, domain, [other_mailbox.id])
    assert res.success is False
    assert res.reason == CannotSetCustomDomainMailboxesCause.InvalidMailbox


def test_set_custom_domain_mailboxes_mailbox_from_current_user_and_another_user():
    other_user = create_new_user()
    other_mailbox = Mailbox.create(
        user_id=other_user.id, email=random_email(), verified=True
    )
    domain = CustomDomain.create(user_id=user.id, domain=random_domain(), commit=True)

    res = set_custom_domain_mailboxes(
        user.id, domain, [user.default_mailbox_id, other_mailbox.id]
    )
    assert res.success is False
    assert res.reason == CannotSetCustomDomainMailboxesCause.InvalidMailbox


def test_set_custom_domain_mailboxes_success():
    other_mailbox = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    domain = CustomDomain.create(user_id=user.id, domain=random_domain(), commit=True)

    res = set_custom_domain_mailboxes(
        user.id, domain, [user.default_mailbox_id, other_mailbox.id]
    )
    assert res.success is True
    assert res.reason is None

    domain_mailboxes = (
        DomainMailbox.filter_by(domain_id=domain.id)
        .order_by(DomainMailbox.mailbox_id.asc())
        .all()
    )
    assert len(domain_mailboxes) == 2
    assert domain_mailboxes[0].domain_id == domain.id
    assert domain_mailboxes[0].mailbox_id == user.default_mailbox_id
    assert domain_mailboxes[1].domain_id == domain.id
    assert domain_mailboxes[1].mailbox_id == other_mailbox.id


def test_set_custom_domain_mailboxes_set_twice():
    other_mailbox = Mailbox.create(user_id=user.id, email=random_email(), verified=True)
    domain = CustomDomain.create(user_id=user.id, domain=random_domain(), commit=True)

    res = set_custom_domain_mailboxes(
        user.id, domain, [user.default_mailbox_id, other_mailbox.id]
    )
    assert res.success is True
    assert res.reason is None

    res = set_custom_domain_mailboxes(
        user.id, domain, [user.default_mailbox_id, other_mailbox.id]
    )
    assert res.success is True
    assert res.reason is None

    domain_mailboxes = (
        DomainMailbox.filter_by(domain_id=domain.id)
        .order_by(DomainMailbox.mailbox_id.asc())
        .all()
    )
    assert len(domain_mailboxes) == 2
    assert domain_mailboxes[0].domain_id == domain.id
    assert domain_mailboxes[0].mailbox_id == user.default_mailbox_id
    assert domain_mailboxes[1].domain_id == domain.id
    assert domain_mailboxes[1].mailbox_id == other_mailbox.id


def test_set_custom_domain_mailboxes_removes_old_association():
    domain = CustomDomain.create(user_id=user.id, domain=random_domain(), commit=True)

    res = set_custom_domain_mailboxes(user.id, domain, [user.default_mailbox_id])
    assert res.success is True
    assert res.reason is None

    other_mailbox = Mailbox.create(
        user_id=user.id, email=random_email(), verified=True, commit=True
    )
    res = set_custom_domain_mailboxes(user.id, domain, [other_mailbox.id])
    assert res.success is True
    assert res.reason is None

    domain_mailboxes = DomainMailbox.filter_by(domain_id=domain.id).all()
    assert len(domain_mailboxes) == 1
    assert domain_mailboxes[0].domain_id == domain.id
    assert domain_mailboxes[0].mailbox_id == other_mailbox.id


def test_set_custom_domain_mailboxes_with_unverified_mailbox():
    domain = CustomDomain.create(user_id=user.id, domain=random_domain())
    verified_mailbox = Mailbox.create(
        user_id=user.id,
        email=random_email(),
        verified=True,
    )
    unverified_mailbox = Mailbox.create(
        user_id=user.id,
        email=random_email(),
        verified=False,
    )

    res = set_custom_domain_mailboxes(
        user.id, domain, [verified_mailbox.id, unverified_mailbox.id]
    )
    assert res.success is False
    assert res.reason is CannotSetCustomDomainMailboxesCause.InvalidMailbox


def test_custom_domain_alias_count():
    user = create_new_user()

    # Test setup
    # Domains:
    # - cd1
    # - cd2
    # - cd3
    # - cd4
    # Aliases:
    # - alias1(active) -> cd1
    # - alias2(active) -> cd1
    # - alias3(active) -> cd2
    # - alias4(trashed) -> cd1
    # - alias5(trashed) -> cd1
    # - alias6(trashed) -> cd2
    # - alias7(trashed) -> cd3
    # Expected counts:
    # - cd1 -> 2 (alias1, alias2)
    # - cd2 -> 1 (alias3)
    # - cd3 -> 0 (alias7 is trashed)
    # - cd4 -> 0

    cd1 = CustomDomain.create(user_id=user.id, domain=random_domain())
    cd2 = CustomDomain.create(user_id=user.id, domain=random_domain())
    cd3 = CustomDomain.create(user_id=user.id, domain=random_domain())
    cd4 = CustomDomain.create(user_id=user.id, domain=random_domain())
    Session.commit()

    def alias_for_domain(domain: CustomDomain, trashed: bool = False) -> Alias:
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

    _alias1 = alias_for_domain(cd1)
    _alias2 = alias_for_domain(cd1)
    _alias3 = alias_for_domain(cd2)
    _alias4 = alias_for_domain(cd1, True)
    _alias5 = alias_for_domain(cd1, True)
    _alias6 = alias_for_domain(cd2, True)
    _alias7 = alias_for_domain(cd3, True)

    assert count_custom_domain_aliases(cd1) == 2
    assert count_custom_domain_aliases(cd2) == 1
    assert count_custom_domain_aliases(cd3) == 0
    assert count_custom_domain_aliases(cd4) == 0
