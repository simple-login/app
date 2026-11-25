"""Tests for the admin domain check page (custom domain creation diagnosis)."""

from flask import url_for

from app.admin.domain_check import diagnose_custom_domain_creation, resolve_user
from app.custom_domain_utils import MAX_UNVERIFIED_CUSTOM_DOMAINS
from app.db import Session
from app.models import CustomDomain, PartnerUser, User
from tests.admin.test_custom_domain_search import login_admin
from tests.utils import (
    create_new_user,
    get_proton_partner,
    random_domain,
    random_string,
)


def _premium_user() -> User:
    user = create_new_user()
    user.trial_end = None
    user.lifetime = True
    Session.flush()
    return user


def test_resolve_user_by_email_id_and_partner_id():
    user = create_new_user()
    external_id = random_string(12)
    PartnerUser.create(
        user_id=user.id,
        partner_id=get_proton_partner().id,
        partner_email=user.email,
        external_user_id=external_id,
        flush=True,
    )

    assert resolve_user(user.email).id == user.id
    assert resolve_user(str(user.id)).id == user.id
    assert resolve_user(f"uid:{user.id}").id == user.id
    assert resolve_user(external_id).id == user.id
    assert resolve_user("nobody@nowhere.lan") is None
    assert resolve_user("") is None


def test_diagnose_reports_pending_domains_and_foreign_parent():
    user = _premium_user()
    for _ in range(MAX_UNVERIFIED_CUSTOM_DOMAINS):
        CustomDomain.create(user_id=user.id, domain=random_domain(), flush=True)
    other_user = create_new_user()
    parent = CustomDomain.create(
        user_id=other_user.id,
        domain=random_domain(),
        ownership_verified=True,
        flush=True,
    )

    diagnosis = diagnose_custom_domain_creation(user, f"b.{parent.domain}")

    assert not diagnosis.check.can_create
    assert diagnosis.check.unverified_limit_reached
    assert len(diagnosis.pending_domains) == MAX_UNVERIFIED_CUSTOM_DOMAINS
    assert [d.id for d in diagnosis.parent_domains] == [parent.id]
    # parent owned by another user must not grant ownership
    assert diagnosis.check.verified_root_cd is None
    assert "pending ownership verification" in diagnosis.explanation


def test_diagnose_explains_not_premium():
    user = create_new_user()
    user.trial_end = None
    Session.flush()

    diagnosis = diagnose_custom_domain_creation(user, random_domain())
    assert "not premium" in diagnosis.explanation


def test_diagnose_explains_domain_used_by_other_user():
    taken = CustomDomain.create(
        user_id=create_new_user().id, domain=random_domain(), flush=True
    )

    diagnosis = diagnose_custom_domain_creation(_premium_user(), taken.domain)
    assert diagnosis.existing_domain.id == taken.id
    assert "another user" in diagnosis.explanation
    assert taken.user.email in diagnosis.explanation


def test_domain_check_page_without_user(flask_client):
    login_admin(flask_client)
    r = flask_client.get(url_for("admin.domain_check.index", domain=random_domain()))
    assert r.status_code == 200
    assert b"add this custom domain" not in r.data
    assert b"No user found" not in r.data


def test_domain_check_page_user_not_found(flask_client):
    login_admin(flask_client)
    r = flask_client.get(
        url_for(
            "admin.domain_check.index",
            domain=random_domain(),
            user="missing@nowhere.lan",
        )
    )
    assert r.status_code == 200
    assert b"No user found" in r.data


def test_domain_check_page_can_add(flask_client):
    login_admin(flask_client)
    user = _premium_user()
    r = flask_client.get(
        url_for("admin.domain_check.index", domain=random_domain(), user=user.email)
    )
    assert r.status_code == 200
    assert b"User can add this custom domain" in r.data


def test_domain_check_page_cannot_add(flask_client):
    login_admin(flask_client)
    user = _premium_user()
    for _ in range(MAX_UNVERIFIED_CUSTOM_DOMAINS):
        CustomDomain.create(user_id=user.id, domain=random_domain(), flush=True)

    r = flask_client.get(
        url_for("admin.domain_check.index", domain=random_domain(), user=user.id)
    )
    assert r.status_code == 200
    assert b"User cannot add this custom domain" in r.data
    assert b"pending ownership verification" in r.data


def test_diagnose_explains_parent_owned_by_other_user():
    other_user = create_new_user()
    parent = CustomDomain.create(
        user_id=other_user.id,
        domain=random_domain(),
        ownership_verified=True,
        flush=True,
    )

    diagnosis = diagnose_custom_domain_creation(_premium_user(), f"b.{parent.domain}")

    assert diagnosis.check.can_create
    assert [d.id for d in diagnosis.foreign_parent_domains] == [parent.id]
    assert "belongs to another user" in diagnosis.explanation
    assert other_user.email in diagnosis.explanation


def test_diagnose_no_parent_note_when_parent_is_own():
    user = _premium_user()
    parent = CustomDomain.create(
        user_id=user.id, domain=random_domain(), ownership_verified=True, flush=True
    )

    diagnosis = diagnose_custom_domain_creation(user, f"b.{parent.domain}")

    assert diagnosis.check.verified_root_cd.id == parent.id
    assert "belongs to another user" not in diagnosis.explanation
