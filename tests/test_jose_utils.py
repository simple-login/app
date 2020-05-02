from app.extensions import db
from app.jose_utils import make_id_token, verify_id_token
from app.models import ClientUser, User, Client


def test_encode_decode(flask_app):
    with flask_app.app_context():
        user = User.create(
            email="a@b.c", password="password", name="Test User", activated=True
        )
        db.session.commit()

        client1 = Client.create_new(name="Demo", user_id=user.id)
        client1.oauth_client_id = "client-id"
        client1.oauth_client_secret = "client-secret"
        client1.published = True
        db.session.commit()

        client_user = ClientUser.create(client_id=client1.id, user_id=user.id)
        db.session.commit()

        jwt_token = make_id_token(client_user)

        assert type(jwt_token) is str
        assert verify_id_token(jwt_token)


def test_db_tear_down(flask_app):
    """make sure the db is reset after each test"""
    with flask_app.app_context():
        assert len(ClientUser.filter_by().all()) == 0
