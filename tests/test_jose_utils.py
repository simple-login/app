from app.extensions import db
from app.jose_utils import make_id_token, verify_id_token
from app.models import ClientUser
from server import fake_data


def test_encode_decode(flask_app):
    with flask_app.app_context():
        fake_data()
        ClientUser.create(client_id=1, user_id=1)
        db.session.commit()
        jwt_token = make_id_token(ClientUser.get(1))

        assert type(jwt_token) is str
        assert verify_id_token(jwt_token)


def test_db_tear_down(flask_app):
    """make sure the db is reset after each test"""
    with flask_app.app_context():
        assert len(ClientUser.filter_by().all()) == 0
