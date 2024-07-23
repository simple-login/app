from typing import Optional

from app.db import Session
from app.log import LOG
from app.models import User, SLDomain, CustomDomain


class CannotSetAlias(Exception):
    def __init__(self, msg: str):
        self.msg = msg


def set_default_alias_domain(user: User, domain_name: Optional[str]):
    if domain_name is None:
        LOG.i(f"User {user} has set no domain as default domain")
        user.default_alias_public_domain_id = None
        user.default_alias_custom_domain_id = None
        Session.flush()
        return
    sl_domain: SLDomain = SLDomain.get_by(domain=domain_name)
    if sl_domain:
        if sl_domain.hidden:
            LOG.i(f"User {user} has tried to set up a hidden domain as default domain")
            raise CannotSetAlias("Domain does not exist")
        if sl_domain.premium_only and not user.is_premium():
            LOG.i(f"User {user} has tried to set up a premium domain as default domain")
            raise CannotSetAlias("You cannot use this domain")
        LOG.i(f"User {user} has set public {sl_domain} as default domain")
        user.default_alias_public_domain_id = sl_domain.id
        user.default_alias_custom_domain_id = None
        Session.flush()
        return
    custom_domain = CustomDomain.get_by(domain=domain_name)
    if not custom_domain:
        LOG.i(
            f"User {user} has tried to set up an non existing domain as default domain"
        )
        raise CannotSetAlias("Domain does not exist or it hasn't been verified")
    if custom_domain.user_id != user.id or not custom_domain.verified:
        LOG.i(
            f"User {user} has tried to set domain {custom_domain} as default domain that does not belong to the user or that is not verified"
        )
        raise CannotSetAlias("Domain does not exist or it hasn't been verified")
    LOG.i(f"User {user} has set custom {custom_domain} as default domain")
    user.default_alias_public_domain_id = None
    user.default_alias_custom_domain_id = custom_domain.id
    Session.flush()
