import pytest

from app import user_settings
from app.db import Session
from app.models import User, CustomDomain, SLDomain
from tests.utils import random_token, create_new_user

user_id: int = 0
custom_domain_id: int = 0
sl_domain_id: int = 0


def setup_module():
    global user_id, custom_domain_id, sl_domain_id
    user = create_new_user()
    user.trial_end = None
    user_id = user.id
    custom_domain_id = CustomDomain.create(
        user_id=user_id,
        catch_all=True,
        domain=random_token() + ".com",
        verified=True,
        flush=True,
    ).id
    sl_domain_id = SLDomain.create(
        domain=random_token() + ".com",
        premium_only=False,
        flush=True,
        order=5,
        hidden=False,
    ).id


def test_set_default_no_domain():
    user = User.get(user_id)
    user.default_alias_public_domain_id = sl_domain_id
    user.default_alias_private_domain_id = custom_domain_id
    Session.flush()
    user_settings.set_default_alias_id(user, None)
    assert user.default_alias_public_domain_id is None
    assert user.default_alias_custom_domain_id is None


def test_set_premium_sl_domain_with_non_premium_user():
    user = User.get(user_id)
    user.lifetime = False
    domain = SLDomain.get(sl_domain_id)
    domain.premium_only = True
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, sl_domain_id)


def test_set_hidden_sl_domain():
    user = User.get(user_id)
    domain = SLDomain.get(sl_domain_id)
    domain.hidden = True
    domain.premium_only = False
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, sl_domain_id)


def test_set_sl_domain():
    user = User.get(user_id)
    user.lifetime = False
    domain = SLDomain.get(sl_domain_id)
    domain.hidden = False
    domain.premium_only = False
    Session.flush()
    user_settings.set_default_alias_id(user, sl_domain_id)
    assert user.default_alias_public_domain_id is sl_domain_id
    assert user.default_alias_custom_domain_id is None


def test_set_sl_premium_domain():
    user = User.get(user_id)
    user.lifetime = True
    domain = SLDomain.get(sl_domain_id)
    domain.hidden = False
    domain.premium_only = True
    Session.flush()
    user_settings.set_default_alias_id(user, sl_domain_id)
    assert user.default_alias_public_domain_id is sl_domain_id
    assert user.default_alias_custom_domain_id is None


def test_set_other_user_custom_domain():
    user = User.get(user_id)
    user.lifetime = True
    other_user_domain_id = CustomDomain.create(
        user_id=create_new_user().id,
        catch_all=True,
        domain=random_token() + ".com",
        verified=True,
    ).id
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, other_user_domain_id)


def test_set_unverified_custom_domain():
    user = User.get(user_id)
    user.lifetime = True
    domain = CustomDomain.get(custom_domain_id)
    domain.verified = False
    Session.flush()
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, custom_domain_id)


def test_set_custom_domain():
    user = User.get(user_id)
    user.lifetime = True
    domain = CustomDomain.get(custom_domain_id)
    domain.verified = True
    Session.flush()
    user_settings.set_default_alias_id(user, custom_domain_id)
    assert user.default_alias_public_domain_id is None
    assert user.default_alias_custom_domain_id is custom_domain_id


def test_set_invalid_custom_domain():
    user = User.get(user_id)
    with pytest.raises(user_settings.CannotSetAlias):
        user_settings.set_default_alias_id(user, 9999999)
