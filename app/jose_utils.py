import base64
import hashlib
from typing import Optional

import arrow
from jwcrypto import jwk, jwt

from app.config import OPENID_PRIVATE_KEY_PATH, URL
from app.log import LOG
from app.models import ClientUser

with open(OPENID_PRIVATE_KEY_PATH, "rb") as f:
    _key = jwk.JWK.from_pem(f.read())


def get_jwk_key() -> dict:
    return _key._public_params()


def make_id_token(
    client_user: ClientUser,
    nonce: Optional[str] = None,
    access_token: Optional[str] = None,
    code: Optional[str] = None,
):
    """Make id_token for OpenID Connect
    According to RFC 7519, these claims are mandatory:
    - iss
    - sub
    - aud
    - exp
    - iat
    """
    claims = {
        "iss": URL,
        "sub": str(client_user.id),
        "aud": client_user.client.oauth_client_id,
        "exp": arrow.now().shift(hours=1).timestamp,
        "iat": arrow.now().timestamp,
        "auth_time": arrow.now().timestamp,
    }

    if nonce:
        claims["nonce"] = nonce

    if access_token:
        claims["at_hash"] = id_token_hash(access_token)

    if code:
        claims["c_hash"] = id_token_hash(code)

    claims = {**claims, **client_user.get_user_info()}

    jwt_token = jwt.JWT(
        header={"alg": "RS256", "kid": _key._public_params()["kid"]}, claims=claims
    )
    jwt_token.make_signed_token(_key)
    return jwt_token.serialize()


def verify_id_token(id_token) -> bool:
    try:
        jwt.JWT(key=_key, jwt=id_token)
    except Exception:
        LOG.e("id token not verified")
        return False
    else:
        return True


def decode_id_token(id_token) -> jwt.JWT:
    return jwt.JWT(key=_key, jwt=id_token)


def id_token_hash(value, hashfunc=hashlib.sha256):
    """
    Inspired from oauthlib
    """
    digest = hashfunc(value.encode()).digest()
    left_most = len(digest) // 2
    return base64.urlsafe_b64encode(digest[:left_most]).decode().rstrip("=")
