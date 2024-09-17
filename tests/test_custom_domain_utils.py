from typing import Optional

from app import config
from app.config import ALIAS_DOMAINS
from app.custom_domain_utils import (
    can_domain_be_used,
    create_custom_domain,
    is_valid_domain,
    sanitize_domain,
    CannotUseDomainReason,
)
from app.db import Session
from app.models import User, CustomDomain, Mailbox
from tests.utils import get_proton_partner
from tests.utils import create_new_user, random_string, random_domain

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
    assert res.can_be_used is True
    assert res.reason is None


def test_can_domain_be_used_existing_domain():
    domain = random_domain()
    CustomDomain.create(user_id=user.id, domain=domain, commit=True)
    res = can_domain_be_used(user, domain)
    assert res.can_be_used is False
    assert res.reason is CannotUseDomainReason.DomainAlreadyUsed


def test_can_domain_be_used_sl_domain():
    domain = ALIAS_DOMAINS[0]
    res = can_domain_be_used(user, domain)
    assert res.can_be_used is False
    assert res.reason is CannotUseDomainReason.BuiltinDomain


def test_can_domain_be_used_domain_of_user_email():
    domain = user.email.split("@")[1]
    res = can_domain_be_used(user, domain)
    assert res.can_be_used is False
    assert res.reason is CannotUseDomainReason.DomainPartOfUserEmail


def test_can_domain_be_used_domain_of_existing_mailbox():
    domain = random_domain()
    Mailbox.create(user_id=user.id, email=f"email@{domain}", verified=True, commit=True)
    res = can_domain_be_used(user, domain)
    assert res.can_be_used is False
    assert res.reason is CannotUseDomainReason.DomainUserInMailbox


def test_can_domain_be_used_invalid_domain():
    domain = f"{random_string(10)}@lol.com"
    res = can_domain_be_used(user, domain)
    assert res.can_be_used is False
    assert res.reason is CannotUseDomainReason.InvalidDomain


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
