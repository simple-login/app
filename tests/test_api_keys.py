from app.db import Session
from app.models import User, ApiKey


def test_create_delete_api_key(flask_client):
    user = User.create(
        email="a@b.c", password="password", name="Test User", activated=True
    )
    Session.commit()

    # create api_key
    api_key = ApiKey.create(user.id, "for test")
    Session.commit()

    assert ApiKey.count() == 1
    assert api_key.name == "for test"

    ApiKey.delete(api_key.id)
    assert ApiKey.count() == 0


def test_delete_all_api_key(flask_client):
    # create two test users
    user_1 = User.create(
        email="a1@b.c", password="password", name="Test User 1", activated=True
    )
    Session.commit()

    user_2 = User.create(
        email="a2@b.c", password="password", name="Test User 2", activated=True
    )
    Session.commit()

    # create api_key for both users
    ApiKey.create(user_1.id, "for test")
    Session.commit()

    ApiKey.create(user_2.id, "for test")
    Session.commit()

    assert (
        ApiKey.count() == 2
    )  # assert that the total number of API keys for all users is 2.
    # assert that each user has a single API key
    assert ApiKey.filter(ApiKey.user_id == user_1.id).count() == 1
    assert ApiKey.filter(ApiKey.user_id == user_2.id).count() == 1

    # delete all of user 1's API keys
    ApiKey.delete_all(user_1.id)
    Session.commit()
    assert (
        ApiKey.count() == 1
    )  # assert that the total number of API keys for all users is now 1.
    assert (
        ApiKey.filter(ApiKey.user_id == user_1.id).count() == 0
    )  # assert that user 1 now has 0 API keys
    assert (
        ApiKey.filter(ApiKey.user_id == user_2.id).count() == 1
    )  # assert that user 2 still has 1 API key
