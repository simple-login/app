import arrow
from jwcrypto import jwk, jwt

from app.config import OPENID_PRIVATE_KEY_PATH, URL
from app.log import LOG
from app.models import ClientUser

with open(OPENID_PRIVATE_KEY_PATH, "rb") as f:
    key = jwk.JWK.from_pem(f.read())


def get_jwk_key() -> dict:
    return key._public_params()


def make_id_token(client_user: ClientUser):
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
    }

    claims = {**claims, **client_user.get_user_info()}

    jwt_token = jwt.JWT(
        header={"alg": "RS256", "kid": key._public_params()["kid"]}, claims=claims
    )
    jwt_token.make_signed_token(key)
    return jwt_token.serialize()


def verify_id_token(id_token) -> bool:
    try:
        jwt.JWT(key=key, jwt=id_token)
    except Exception:
        LOG.exception("id token not verified")
        return False
    else:
        return True
