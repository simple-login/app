"""
The Paddle checkout is opened by the browser, so the "passthrough" field that
tells us which account to credit is under the buyer's control. Paddle signs the
webhook, which proves the payload reaches us unmodified, but it says nothing
about the buyer being entitled to the account named in the passthrough.

We therefore sign the passthrough ourselves when rendering the checkout and only
accept a passthrough that carries our own signature.

PADDLE_ALLOW_UNSIGNED_PASSTHROUGH reopens the legacy unsigned format for the
duration of the transition, so that a checkout opened just before the deploy
still credits its buyer. It is meant to be unset again shortly after.
"""

import json
from typing import Optional

import itsdangerous

from app import config
from app.log import LOG

serializer = itsdangerous.URLSafeTimedSerializer(config.PADDLE_PASSTHROUGH_SECRET)

# a checkout can stay open for a while and Paddle retries failed webhooks for
# several days, so the token is deliberately long-lived
_MAX_AGE_SECONDS = 7 * 24 * 3600


def sign_passthrough(user_id: int) -> str:
    """Build the passthrough handed to Paddle.Checkout.open()"""
    return serializer.dumps({"user_id": user_id})


def _user_id_from(payload) -> Optional[int]:
    """The user_id of a decoded passthrough payload, if it holds a plausible one"""
    if not isinstance(payload, dict):
        return None

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        return None

    return user_id


def _legacy_user_id(passthrough: str) -> Optional[int]:
    """
    Read the pre-fix passthrough, ie '{"user_id": 88 }'.

    The buyer can set this freely, so it grants nothing on its own: the caller
    still refuses to hand over the subscription of a user who has an active one.
    Only reachable while PADDLE_ALLOW_UNSIGNED_PASSTHROUGH is set.
    """
    try:
        payload = json.loads(passthrough)
    except ValueError:
        LOG.e("Paddle passthrough is neither signed nor legacy json %s", passthrough)
        return None

    user_id = _user_id_from(payload)
    if user_id is None:
        LOG.e("Legacy Paddle passthrough without a user_id %s", passthrough)
        return None

    LOG.w(
        "Accepting legacy unsigned Paddle passthrough for user %s. Unset "
        "PADDLE_ALLOW_UNSIGNED_PASSTHROUGH once these stop appearing",
        user_id,
    )
    return user_id


def verify_passthrough(passthrough: Optional[str]) -> Optional[int]:
    """Return the user_id carried by a passthrough we signed, None otherwise"""
    if not passthrough:
        return None

    try:
        payload = serializer.loads(passthrough, max_age=_MAX_AGE_SECONDS)
    except itsdangerous.SignatureExpired:
        LOG.w("Expired Paddle passthrough %s", passthrough)
        return None
    except itsdangerous.BadSignature:
        # might be a checkout opened before the signed passthrough was deployed
        if config.PADDLE_ALLOW_UNSIGNED_PASSTHROUGH:
            return _legacy_user_id(passthrough)
        LOG.e("Tampered Paddle passthrough %s", passthrough)
        return None

    user_id = _user_id_from(payload)
    if user_id is None:
        LOG.e("Signed Paddle passthrough without a user_id %s", payload)
        return None

    return user_id
