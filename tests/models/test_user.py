from app.models import User


def test_available_sl_domains(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )

    assert set(user.available_sl_domains()) == {"d1.test", "d2.test", "sl.local"}
