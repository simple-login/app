from app.db import Session
from app.jose_utils import make_id_token, verify_id_token
from app.models import ClientUser, Client
from tests.utils import create_new_user


def test_encode_decode(flask_client):
    user = create_new_user()

    client1 = Client.create_new(name="Demo", user_id=user.id)
    client1.oauth_client_id = "client-id"
    client1.oauth_client_secret = "client-secret"
    Session.commit()

    client_user = ClientUser.create(client_id=client1.id, user_id=user.id)
    Session.commit()

    jwt_token = make_id_token(client_user)

    assert type(jwt_token) is str
    assert verify_id_token(jwt_token)


def test_db_tear_down(flask_client):
    """make sure the db is reset after each test"""
    assert len(ClientUser.filter_by().all()) == 0
