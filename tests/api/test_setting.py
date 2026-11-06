from app.db import Session
from app.models import (
    CustomDomain,
    PartnerUser,
    AliasGeneratorEnum,
    SenderFormatEnum,
    AliasSuffixEnum,
)
from tests.api.utils import get_new_user_and_api_key
from tests.utils import (
    create_partner_linked_user,
    enter_sudo_mode,
    exit_sudo_mode,
    login,
    random_domain,
    random_token,
)


def test_get_setting(flask_client):
    login(flask_client)

    r = flask_client.get("/api/setting")
    assert r.status_code == 200
    assert r.json == {
        "alias_generator": "word",
        "notification": True,
        "random_alias_default_domain": "sl.lan",
        "sender_format": "AT",
        "random_alias_suffix": "word",
    }


def test_update_settings_notification(flask_client):
    user = login(flask_client)
    assert user.notification

    r = flask_client.patch("/api/setting", json={"notification": False})
    assert r.status_code == 200
    assert not user.notification


def test_update_settings_alias_generator(flask_client):
    user = login(flask_client)
    assert user.alias_generator == AliasGeneratorEnum.word.value

    r = flask_client.patch("/api/setting", json={"alias_generator": "invalid"})
    assert r.status_code == 400

    r = flask_client.patch("/api/setting", json={"alias_generator": "uuid"})
    assert r.status_code == 200
    assert user.alias_generator == AliasGeneratorEnum.uuid.value


def test_update_settings_random_alias_default_domain(flask_client):
    user = login(flask_client)
    custom_domain = CustomDomain.create(
        domain=random_domain(),
        verified=True,
        ownership_verified=True,
        user_id=user.id,
        flush=True,
    )
    assert user.default_random_alias_domain() == "sl.lan"

    r = flask_client.patch(
        "/api/setting", json={"random_alias_default_domain": "invalid"}
    )
    assert r.status_code == 400

    r = flask_client.patch(
        "/api/setting", json={"random_alias_default_domain": "d1.lan"}
    )
    assert r.status_code == 200
    assert user.default_random_alias_domain() == "d1.lan"

    r = flask_client.patch(
        "/api/setting", json={"random_alias_default_domain": custom_domain.domain}
    )
    assert r.status_code == 200
    assert user.default_random_alias_domain() == custom_domain.domain


def test_update_settings_random_alias_default_domain_without_ownership(flask_client):
    user = login(flask_client)
    custom_domain = CustomDomain.create(
        domain=random_domain(),
        verified=True,
        ownership_verified=False,
        user_id=user.id,
        flush=True,
    )

    r = flask_client.patch(
        "/api/setting", json={"random_alias_default_domain": custom_domain.domain}
    )
    assert r.status_code == 400
    assert user.default_alias_custom_domain_id is None


def test_update_settings_sender_format(flask_client):
    user = login(flask_client)
    assert user.sender_format == SenderFormatEnum.AT.value

    r = flask_client.patch("/api/setting", json={"sender_format": "invalid"})
    assert r.status_code == 400

    r = flask_client.patch("/api/setting", json={"sender_format": "A"})
    assert r.status_code == 200
    assert user.sender_format == SenderFormatEnum.A.value

    r = flask_client.patch("/api/setting", json={"sender_format": "NAME_ONLY"})
    assert r.status_code == 200
    assert user.sender_format == SenderFormatEnum.NAME_ONLY.value


def test_get_setting_domains(flask_client):
    user = login(flask_client)
    domain = random_domain()
    CustomDomain.create(user_id=user.id, domain=domain, verified=True, commit=True)

    r = flask_client.get("/api/setting/domains")
    assert r.status_code == 200


def test_get_setting_domains_v2(flask_client):
    user = login(flask_client)
    domain = random_domain()
    CustomDomain.create(user_id=user.id, domain=domain, verified=True, commit=True)

    r = flask_client.get("/api/v2/setting/domains")
    assert r.status_code == 200


def test_update_settings_random_alias_suffix(flask_client):
    user = login(flask_client)
    # default random_alias_suffix is random_string
    assert user.random_alias_suffix == AliasSuffixEnum.word.value

    r = flask_client.patch("/api/setting", json={"random_alias_suffix": "invalid"})
    assert r.status_code == 400

    r = flask_client.patch(
        "/api/setting", json={"random_alias_suffix": "random_string"}
    )
    assert r.status_code == 200
    assert user.random_alias_suffix == AliasSuffixEnum.random_string.value


def _link_proton_account(user):
    from app.proton.proton_partner import get_proton_partner

    PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        external_user_id=random_token(10),
        flush=True,
    )


def test_unlink_proton_account_requires_sudo(flask_client):
    user = login(flask_client)
    _link_proton_account(user)
    # password login grants sudo; simulate a session whose sudo has expired
    exit_sudo_mode(flask_client)

    r = flask_client.delete("/api/setting/unlink_proton_account")
    assert r.status_code == 440


def test_unlink_proton_account_with_session_sudo(flask_client):
    user = login(flask_client)
    _link_proton_account(user)
    enter_sudo_mode(flask_client, user)

    r = flask_client.delete("/api/setting/unlink_proton_account")
    assert r.status_code == 200
    assert r.json == {"ok": True}


def test_unlink_proton_account_with_api_key_no_sudo(flask_client):
    user, api_key = get_new_user_and_api_key()
    _link_proton_account(user)

    r = flask_client.delete(
        "/api/setting/unlink_proton_account",
        headers={"Authentication": api_key.code},
    )
    assert r.status_code == 440


def test_unlink_proton_account_created_from_partner_cannot_unlink(flask_client):
    user, _ = create_partner_linked_user()
    user.flags |= user.FLAG_CREATED_FROM_PARTNER
    Session.commit()
    login(flask_client, user)
    enter_sudo_mode(flask_client, user)

    r = flask_client.delete("/api/setting/unlink_proton_account")
    assert r.status_code == 400
