import arrow

from app.db import Session
from app.models import OauthToken, Client
from app.utils import random_string
from tasks.cleanup_expired_oauth_token import cleanup_expired_oauth_tokens
from tests.utils import create_new_user


def test_cleanup_expired_oauth_tokens():
    OauthToken.filter().delete()

    user = create_new_user()
    client = Client.create_new(name="Test Client", user_id=user.id)
    Session.commit()

    now = arrow.now()
    cutoff_time = now.shift(hours=-1)

    # Token expired 2 hours ago - should be deleted
    token_old_expired = OauthToken.create(
        access_token=random_string(128),
        client_id=client.id,
        user_id=user.id,
        expired=now.shift(hours=-2),
        flush=True,
    )
    token_old_expired_id = token_old_expired.id

    # Token expired exactly at cutoff time - should NOT be deleted (< not <=)
    token_at_cutoff = OauthToken.create(
        access_token=random_string(128),
        client_id=client.id,
        user_id=user.id,
        expired=cutoff_time,
        flush=True,
    )
    token_at_cutoff_id = token_at_cutoff.id

    # Token expired 30 minutes ago - should NOT be deleted (newer than cutoff)
    token_recent_expired = OauthToken.create(
        access_token=random_string(128),
        client_id=client.id,
        user_id=user.id,
        expired=now.shift(minutes=-30),
        flush=True,
    )
    token_recent_expired_id = token_recent_expired.id

    # Token not yet expired - should NOT be deleted
    token_not_expired = OauthToken.create(
        access_token=random_string(128),
        client_id=client.id,
        user_id=user.id,
        expired=now.shift(hours=1),
        flush=True,
    )
    token_not_expired_id = token_not_expired.id

    # Token with NULL expired field - should NOT be deleted
    token_null_expired = OauthToken.create(
        access_token=random_string(128),
        client_id=client.id,
        user_id=user.id,
        expired=None,
        flush=True,
    )
    token_null_expired_id = token_null_expired.id

    # Run cleanup
    cleanup_expired_oauth_tokens(cutoff_time)

    # Verify only the old expired token was deleted
    assert OauthToken.get(token_old_expired_id) is None
    assert OauthToken.get(token_at_cutoff_id) is not None
    assert OauthToken.get(token_recent_expired_id) is not None
    assert OauthToken.get(token_not_expired_id) is not None
    assert OauthToken.get(token_null_expired_id) is not None


def test_cleanup_expired_oauth_tokens_multiple():
    OauthToken.filter().delete()

    user = create_new_user()
    client = Client.create_new(name="Test Client", user_id=user.id)
    Session.commit()

    now = arrow.now()
    cutoff_time = now.shift(days=-7)

    # Create multiple old expired tokens that should be deleted
    old_token_ids = []
    for i in range(5):
        token = OauthToken.create(
            access_token=random_string(128),
            client_id=client.id,
            user_id=user.id,
            expired=cutoff_time.shift(days=-i - 1),  # All older than cutoff
            flush=True,
        )
        old_token_ids.append(token.id)

    # Create tokens that should be kept
    keep_token_ids = []
    for i in range(3):
        token = OauthToken.create(
            access_token=random_string(128),
            client_id=client.id,
            user_id=user.id,
            expired=cutoff_time.shift(days=i + 1),  # All newer than cutoff
            flush=True,
        )
        keep_token_ids.append(token.id)

    # Run cleanup
    cleanup_expired_oauth_tokens(cutoff_time)

    # Verify all old tokens were deleted
    for token_id in old_token_ids:
        assert OauthToken.get(token_id) is None

    # Verify all recent tokens were kept
    for token_id in keep_token_ids:
        assert OauthToken.get(token_id) is not None


def test_cleanup_expired_oauth_tokens_empty():
    OauthToken.filter().delete()

    user = create_new_user()
    client = Client.create_new(name="Test Client", user_id=user.id)
    Session.commit()

    now = arrow.now()
    cutoff_time = now.shift(days=-7)

    # Create only non-expired tokens
    token = OauthToken.create(
        access_token=random_string(128),
        client_id=client.id,
        user_id=user.id,
        expired=now.shift(hours=1),
        flush=True,
    )

    # Run cleanup - should not delete anything
    cleanup_expired_oauth_tokens(cutoff_time)

    # Verify token still exists
    assert OauthToken.get(token.id) is not None


def test_cleanup_expired_oauth_tokens_multiple_clients():
    OauthToken.filter().delete()

    user1 = create_new_user()
    user2 = create_new_user()
    client1 = Client.create_new(name="Client 1", user_id=user1.id)
    client2 = Client.create_new(name="Client 2", user_id=user2.id)
    Session.commit()

    now = arrow.now()
    cutoff_time = now.shift(days=-7)

    # Create expired tokens for different clients/users
    token1_old = OauthToken.create(
        access_token=random_string(128),
        client_id=client1.id,
        user_id=user1.id,
        expired=cutoff_time.shift(days=-1),
        flush=True,
    )
    token1_old_id = token1_old.id

    token2_old = OauthToken.create(
        access_token=random_string(128),
        client_id=client2.id,
        user_id=user2.id,
        expired=cutoff_time.shift(days=-1),
        flush=True,
    )
    token2_old_id = token2_old.id

    token1_new = OauthToken.create(
        access_token=random_string(128),
        client_id=client1.id,
        user_id=user1.id,
        expired=cutoff_time.shift(days=1),
        flush=True,
    )
    token1_new_id = token1_new.id

    token2_new = OauthToken.create(
        access_token=random_string(128),
        client_id=client2.id,
        user_id=user2.id,
        expired=cutoff_time.shift(days=1),
        flush=True,
    )
    token2_new_id = token2_new.id

    # Run cleanup
    cleanup_expired_oauth_tokens(cutoff_time)

    # Verify old tokens from both clients were deleted
    assert OauthToken.get(token1_old_id) is None
    assert OauthToken.get(token2_old_id) is None

    # Verify new tokens from both clients were kept
    assert OauthToken.get(token1_new_id) is not None
    assert OauthToken.get(token2_new_id) is not None
