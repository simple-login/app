from app.models import Partner, PartnerApiToken
from app.utils import random_string


def test_generate_partner_api_token(flask_client):
    partner = Partner.create(
        name=random_string(10),
        contact_email="{s}@{s}.com".format(s=random_string(10)),
        commit=True,
    )

    partner_api_token, token = PartnerApiToken.generate(partner.id, None)

    assert token is not None
    assert len(token) > 0

    assert partner_api_token.partner_id == partner.id
    assert partner_api_token.expiration_time is None

    hmaced = PartnerApiToken.hmac_token(token)
    assert hmaced == partner_api_token.token

    retrieved_partner = Partner.find_by_token(token)
    assert retrieved_partner is not None
    assert retrieved_partner.id == partner.id
