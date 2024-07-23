import pytest

from app import user_settings
from app.db import Session
from app.models import User, CustomDomain, SLDomain
from tests.utils import random_token, create_new_user

user_id: int = 0
custom_domain_name: str = ""
sl_domain_name: str = ""


def setup_module():
    global user_id, custom_domain_name, sl_domain_name
    user = create_new_user()
    user.trial_end = None
    user_id = user.id
    custom_domain_name = CustomDomain.create(
        user_id=user_id,
        catch_all=True,
        domain=random_token() + ".com",
        verified=True,
        flush=True,
    ).domain
    sl_domain_name = SLDomain.create(
        domain=random_token() + ".com",
        premium_only=False,
        flush=True,
        order=5,
        hidden=False,
    ).domain


def test_set_default_no_domain():
    user = User.get(user_id)
    user.default_alias_public_domain_id = SLDomain.get_by(domain=sl_domain_name).id
    user.default_alias_private_domain_id = CustomDomain.get_by(
        domain=custom_domain_name
    ).id
    Session.flush()
    user_settings.set_default_alias_id(user, None)
    assert user.default_alias_public_domain_id is None
    assert user.default_alias_custom_domain_id is None


def test_set_premium_sl_domain_with_non_premium_user():
    user = User.get(user_id)
    user.lifetime = False
    domain = SLDomain.get_by(domain=sl_domain_name)
    domain.premium_only = True
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, sl_domain_name)


def test_set_hidden_sl_domain():
    user = User.get(user_id)
    domain = SLDomain.get_by(domain=sl_domain_name)
    domain.hidden = True
    domain.premium_only = False
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, sl_domain_name)


def test_set_sl_domain():
    user = User.get(user_id)
    user.lifetime = False
    domain = SLDomain.get_by(domain=sl_domain_name)
    domain.hidden = False
    domain.premium_only = False
    Session.flush()
    user_settings.set_default_alias_id(user, sl_domain_name)
    assert user.default_alias_public_domain_id == domain.id
    assert user.default_alias_custom_domain_id is None


def test_set_sl_premium_domain():
    user = User.get(user_id)
    user.lifetime = True
    domain = SLDomain.get_by(domain=sl_domain_name)
    domain.hidden = False
    domain.premium_only = True
    Session.flush()
    user_settings.set_default_alias_id(user, sl_domain_name)
    assert user.default_alias_public_domain_id == domain.id
    assert user.default_alias_custom_domain_id is None


def test_set_other_user_custom_domain():
    user = User.get(user_id)
    user.lifetime = True
    other_user_domain_name = CustomDomain.create(
        user_id=create_new_user().id,
        catch_all=True,
        domain=random_token() + ".com",
        verified=True,
    ).domain
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, other_user_domain_name)


def test_set_unverified_custom_domain():
    user = User.get(user_id)
    user.lifetime = True
    domain = CustomDomain.get_by(domain=custom_domain_name)
    domain.verified = False
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, custom_domain_name)


def test_set_custom_domain():
    user = User.get(user_id)
    user.lifetime = True
    domain = CustomDomain.get_by(domain=custom_domain_name)
    domain.verified = True
    Session.flush()
    user_settings.set_default_alias_id(user, custom_domain_name)
    assert user.default_alias_public_domain_id is None
    assert user.default_alias_custom_domain_id == domain.id


def test_set_invalid_custom_domain():
    user = User.get(user_id)
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, "invalid_nop" + random_token())
