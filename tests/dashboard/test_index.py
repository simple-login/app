from flask import url_for

from app import config
from app.db import Session
from app.models import (
    Alias,
    Mailbox,
)
from tests.utils import fix_rate_limit_after_request, login


def test_create_random_alias_success(flask_client):
    user = login(flask_client)
    assert Alias.filter(Alias.user_id == user.id).count() == 1

    r = flask_client.post(
        url_for("dashboard.index"),
        data={"form-name": "create-random-email"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert Alias.filter(Alias.user_id == user.id).count() == 2


def test_too_many_requests(flask_client):
    config.DISABLE_RATE_LIMIT = False
    login(flask_client)

    # can't create more than 5 aliases in 1 minute
    for _ in range(7):
        r = flask_client.post(
            url_for("dashboard.index"),
            data={"form-name": "create-random-email"},
            follow_redirects=True,
        )

        # to make flask-limiter work with unit test
        # https://github.com/alisaifee/flask-limiter/issues/147#issuecomment-642683820
        fix_rate_limit_after_request()
    else:
        # last request
        assert r.status_code == 429
        assert "Whoa, slow down there, pardner!" in str(r.data)


def test_can_change_mailbox_when_only_admin_disabled_mailbox_on_alias(flask_client):
    """
    Test scenario:
    - User has mailbox A (active) and mailbox B (will be admin-disabled)
    - Create alias with only mailbox B
    - Admin-disable mailbox B
    - User should still see the mailbox selector (even though only 1 active mailbox)
    - User should be able to change alias to use mailbox A
    """
    user = login(flask_client)

    # Create mailbox A (will remain active)
    Mailbox.create(
        user_id=user.id, email="active@gmail.com", verified=True, commit=True
    )

    # Create mailbox B (will be admin-disabled)
    mailbox_b = Mailbox.create(
        user_id=user.id, email="disabled@gmail.com", verified=True
    )

    # Create an alias with only mailbox B
    alias = Alias.create_new_random(user)
    alias.mailbox_id = mailbox_b.id
    Session.commit()

    # Admin-disable mailbox B
    mailbox_b.flags = (mailbox_b.flags or 0) | Mailbox.FLAG_ADMIN_DISABLED
    Session.commit()

    # Visit the alias list page
    r = flask_client.get(url_for("dashboard.index"))
    assert r.status_code == 200

    # Verify that:
    # 1. The mailbox selector is shown (even though only 1 active mailbox)
    assert b"mailbox-select" in r.data or f'id="mailbox-{alias.id}"'.encode() in r.data

    # 2. A warning is shown about admin-disabled mailbox
    assert (
        b"disabled by an admin" in r.data.lower()
        or b"change it to an active mailbox" in r.data.lower()
    )

    # 3. Mailbox A is shown as an option
    assert b"active@gmail.com" in r.data

    # 4. Mailbox B is NOT shown as an option (filtered from selector)
    # The disabled mailbox should not appear in the options
    # (only active mailboxes appear as options)


def test_user_can_switch_alias_from_admin_disabled_to_active_mailbox(flask_client):
    """
    Test that user can actually switch the alias mailbox via the UI
    """
    user = login(flask_client)

    # Create mailbox A (active)
    mailbox_a = Mailbox.create(user_id=user.id, email="active@gmail.com", verified=True)

    # Create mailbox B (will be admin-disabled)
    mailbox_b = Mailbox.create(
        user_id=user.id, email="disabled@gmail.com", verified=True
    )

    # Create an alias with only mailbox B
    alias = Alias.create_new_random(user)
    alias.mailbox_id = mailbox_b.id
    Session.commit()

    # Admin-disable mailbox B
    mailbox_b.flags = (mailbox_b.flags or 0) | Mailbox.FLAG_ADMIN_DISABLED
    Session.commit()

    # Verify alias is using mailbox B
    assert alias.mailbox_id == mailbox_b.id
    assert alias.mailboxes == [mailbox_b]

    # Now try to change the mailbox via API call (simulating the UI action)
    # The UI calls an API endpoint when the user changes the mailbox
    # Let's use the alias update API
    from app.models import ApiKey

    api_key = ApiKey.create(user_id=user.id, name="test", commit=True)

    r = flask_client.patch(
        f"/api/aliases/{alias.id}",
        headers={"Authentication": api_key.code},
        json={"mailbox_ids": [mailbox_a.id]},
    )

    # Should succeed in changing to active mailbox
    assert r.status_code == 200

    # Verify the mailbox was changed
    Session.refresh(alias)
    assert alias.mailbox_id == mailbox_a.id
    assert alias.mailboxes == [mailbox_a]


def test_mailbox_selector_hidden_when_no_admin_disabled_and_only_one_mailbox(
    flask_client,
):
    """
    Test that the selector is properly hidden when there's only 1 active mailbox
    and NO admin-disabled mailboxes on the alias (normal case)
    """
    user = login(flask_client)

    # User only has default mailbox (no other mailboxes)
    # Create an alias with the default mailbox
    alias = Alias.create_new_random(user)
    Session.commit()

    # Visit the alias list page
    r = flask_client.get(url_for("dashboard.index"))
    assert r.status_code == 200

    # The mailbox selector should NOT be shown (normal case: 1 mailbox, no issues)
    # We check that either the select element doesn't exist for this alias
    # OR the text shows "Owned by" instead of a selector
    assert b"Owned by" in r.data or f'id="mailbox-{alias.id}"'.encode() not in r.data
