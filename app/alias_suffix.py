from __future__ import annotations
import json
from dataclasses import asdict, dataclass
from typing import Optional

import itsdangerous
from app import config
from app.log import LOG
from app.models import User, AliasOptions, SLDomain

signer = itsdangerous.TimestampSigner(config.CUSTOM_ALIAS_SECRET)


@dataclass
class AliasSuffix:
    # whether this is a custom domain
    is_custom: bool
    # Suffix
    suffix: str
    # Suffix signature
    signed_suffix: str
    # whether this is a premium SL domain. Not apply to custom domain
    is_premium: bool
    # can be either Custom or SL domain
    domain: str
    # if custom domain, whether the custom domain has MX verified, i.e. can receive emails
    mx_verified: bool = True

    def serialize(self):
        return json.dumps(asdict(self))

    @classmethod
    def deserialize(cls, data: str) -> AliasSuffix:
        return AliasSuffix(**json.loads(data))


def check_suffix_signature(signed_suffix: str) -> Optional[str]:
    # hypothesis: user will click on the button in the 600 secs
    try:
        return signer.unsign(signed_suffix, max_age=600).decode()
    except itsdangerous.BadSignature:
        return None


def verify_prefix_suffix(
    user: User, alias_prefix, alias_suffix, alias_options: Optional[AliasOptions] = None
) -> bool:
    """verify if user could create an alias with the given prefix and suffix"""
    if not alias_prefix or not alias_suffix:  # should be caught on frontend
        return False

    user_custom_domains = [cd.domain for cd in user.verified_custom_domains()]

    # make sure alias_suffix is either .random_word@simplelogin.co or @my-domain.com
    alias_suffix = alias_suffix.strip()
    # alias_domain_prefix is either a .random_word or ""
    alias_domain_prefix, alias_domain = alias_suffix.split("@", 1)

    # alias_domain must be either one of user custom domains or built-in domains
    if alias_domain not in user.available_alias_domains(alias_options=alias_options):
        LOG.i("wrong alias suffix %s, user %s", alias_suffix, user)
        return False

    # SimpleLogin domain case:
    # 1) alias_suffix must start with "." and
    # 2) alias_domain_prefix must come from the word list
    available_sl_domains = [
        sl_domain.domain
        for sl_domain in user.get_sl_domains(alias_options=alias_options)
    ]
    if (
        alias_domain in available_sl_domains
        and alias_domain not in user_custom_domains
        # when DISABLE_ALIAS_SUFFIX is true, alias_domain_prefix is empty
        and not config.DISABLE_ALIAS_SUFFIX
    ):
        if not alias_domain_prefix.startswith("."):
            LOG.i("User %s submits a wrong alias suffix %s", user, alias_suffix)
            return False

    else:
        if alias_domain not in user_custom_domains:
            if not config.DISABLE_ALIAS_SUFFIX:
                LOG.i("wrong alias suffix %s, user %s", alias_suffix, user)
                return False

            if alias_domain not in available_sl_domains:
                LOG.i("wrong alias suffix %s, user %s", alias_suffix, user)
                return False

    return True


def get_alias_suffixes(
    user: User, alias_options: Optional[AliasOptions] = None
) -> [AliasSuffix]:
    """
    Similar to as get_available_suffixes() but also return custom domain that doesn't have MX set up.
    """
    user_custom_domains = user.verified_custom_domains()

    alias_suffixes: [AliasSuffix] = []

    # put custom domain first
    # for each user domain, generate both the domain and a random suffix version
    for custom_domain in user_custom_domains:
        if custom_domain.random_prefix_generation:
            suffix = (
                f".{user.get_random_alias_suffix(custom_domain)}@{custom_domain.domain}"
            )
            alias_suffix = AliasSuffix(
                is_custom=True,
                suffix=suffix,
                signed_suffix=signer.sign(suffix).decode(),
                is_premium=False,
                domain=custom_domain.domain,
                mx_verified=custom_domain.verified,
            )
            if user.default_alias_custom_domain_id == custom_domain.id:
                alias_suffixes.insert(0, alias_suffix)
            else:
                alias_suffixes.append(alias_suffix)

        suffix = f"@{custom_domain.domain}"
        alias_suffix = AliasSuffix(
            is_custom=True,
            suffix=suffix,
            signed_suffix=signer.sign(suffix).decode(),
            is_premium=False,
            domain=custom_domain.domain,
            mx_verified=custom_domain.verified,
        )

        # put the default domain to top
        # only if random_prefix_generation isn't enabled
        if (
            user.default_alias_custom_domain_id == custom_domain.id
            and not custom_domain.random_prefix_generation
        ):
            alias_suffixes.insert(0, alias_suffix)
        else:
            alias_suffixes.append(alias_suffix)

    # then SimpleLogin domain
    sl_domains = user.get_sl_domains(alias_options=alias_options)
    default_domain_found = False
    for sl_domain in sl_domains:
        prefix = (
            "" if config.DISABLE_ALIAS_SUFFIX else f".{user.get_random_alias_suffix()}"
        )
        suffix = f"{prefix}@{sl_domain.domain}"
        alias_suffix = AliasSuffix(
            is_custom=False,
            suffix=suffix,
            signed_suffix=signer.sign(suffix).decode(),
            is_premium=sl_domain.premium_only,
            domain=sl_domain.domain,
            mx_verified=True,
        )
        # No default or this is not the default
        if (
            user.default_alias_public_domain_id is None
            or user.default_alias_public_domain_id != sl_domain.id
        ):
            alias_suffixes.append(alias_suffix)
        else:
            default_domain_found = True
            alias_suffixes.insert(0, alias_suffix)

    if not default_domain_found:
        domain_conditions = {"id": user.default_alias_public_domain_id, "hidden": False}
        if not user.is_premium():
            domain_conditions["premium_only"] = False
        sl_domain = SLDomain.get_by(**domain_conditions)
        if sl_domain:
            prefix = (
                ""
                if config.DISABLE_ALIAS_SUFFIX
                else f".{user.get_random_alias_suffix()}"
            )
            suffix = f"{prefix}@{sl_domain.domain}"
            alias_suffix = AliasSuffix(
                is_custom=False,
                suffix=suffix,
                signed_suffix=signer.sign(suffix).decode(),
                is_premium=sl_domain.premium_only,
                domain=sl_domain.domain,
                mx_verified=True,
            )
            alias_suffixes.insert(0, alias_suffix)

    return alias_suffixes
