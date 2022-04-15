from tests.utils import create_new_user


def test_available_sl_domains(flask_client):
    user = create_new_user()

    assert set(user.available_sl_domains()) == {"d1.test", "d2.test", "sl.local"}
