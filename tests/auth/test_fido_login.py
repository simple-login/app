import uuid
from typing import Tuple

from unittest.mock import patch

import webauthn
from flask.testing import FlaskClient

from app.config import MFA_USER_ID
from app.db import Session
from app.models import Fido, User
from tests.utils import create_new_user


def _create_fido_user(sign_count: int = 0) -> Tuple[User, Fido]:
    user = create_new_user()
    user.fido_uuid = str(uuid.uuid4())
    # fido.uuid has an FK on users.fido_uuid, so persist it before the key
    Session.commit()
    fido_key = Fido.create(
        credential_id="cred-" + uuid.uuid4().hex,
        uuid=user.fido_uuid,
        public_key="pk-" + uuid.uuid4().hex,
        sign_count=sign_count,
        name="Test Key",
        user_id=user.id,
        flush=True,
    )
    Session.commit()
    return user, fido_key


def _start_mfa_session(flask_client: FlaskClient, user: User):
    with flask_client.session_transaction() as sess:
        sess[MFA_USER_ID] = user.id


def _post_fido_assertion(flask_client: FlaskClient, fido_key: Fido, challenge: str):
    with flask_client.session_transaction() as sess:
        sess["fido_challenge"] = challenge
    return flask_client.post(
        "/auth/fido",
        data={"sk_assertion": '{"id": "%s"}' % fido_key.credential_id},
    )


def test_fido_login_updates_stored_sign_count(flask_client):
    """A successful WebAuthn login must persist the new sign count on the
    Fido row so cloned-authenticator detection keeps working (SECBTY-2412)."""
    user, fido_key = _create_fido_user(sign_count=7)
    _start_mfa_session(flask_client, user)
    with patch("webauthn.WebAuthnAssertionResponse.verify", return_value=42):
        r = _post_fido_assertion(flask_client, fido_key, "challenge")
    assert r.status_code == 302

    Session.expire_all()
    assert Fido.get_by(id=fido_key.id).sign_count == 42


def test_fido_login_failure_leaves_sign_count_unchanged(flask_client):
    """A rejected assertion must not advance the stored counter nor log in."""
    user, fido_key = _create_fido_user(sign_count=7)
    _start_mfa_session(flask_client, user)
    with patch(
        "webauthn.WebAuthnAssertionResponse.verify",
        side_effect=webauthn.webauthn.AuthenticationRejectedException(
            "Duplicate authentication detected."
        ),
    ):
        r = _post_fido_assertion(flask_client, fido_key, "challenge")
    # verification failed: re-rendered form, no login redirect
    assert r.status_code == 200

    Session.expire_all()
    assert Fido.get_by(id=fido_key.id).sign_count == 7
    with flask_client.session_transaction() as sess:
        # MFA_USER_ID is kept (no login) and no user id in session
        assert sess.get(MFA_USER_ID) == user.id
        assert "_user_id" not in sess
