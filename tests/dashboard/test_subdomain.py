from flask import url_for

from app.config import MAX_NB_SUBDOMAIN
from app.db import Session
from app.models import SLDomain, CustomDomain, Job
from tests.utils import login


def setup_sl_domain() -> SLDomain:
    """Take the first SLDomain and set its can_use_subdomain=True"""
    sl_domain: SLDomain = SLDomain.first()
    sl_domain.can_use_subdomain = True
    Session.commit()

    return sl_domain


def test_create_subdomain(flask_client):
    login(flask_client)
    sl_domain = setup_sl_domain()

    r = flask_client.post(
        url_for("dashboard.subdomain_route"),
        data={"form-name": "create", "subdomain": "test", "domain": sl_domain.domain},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"New subdomain test.{sl_domain.domain} is created" in r.data.decode()
    assert CustomDomain.get_by(domain=f"test.{sl_domain.domain}") is not None


def test_delete_subdomain(flask_client):
    user = login(flask_client)
    sl_domain = setup_sl_domain()

    subdomain = CustomDomain.create(
        domain=f"test.{sl_domain.domain}",
        user_id=user.id,
        is_sl_subdomain=True,
        commit=True,
    )

    nb_job = Job.count()

    r = flask_client.post(
        url_for("dashboard.domain_detail", custom_domain_id=subdomain.id),
        data={"form-name": "delete"},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert f"test.{sl_domain.domain} scheduled for deletion." in r.data.decode()

    # a domain deletion job is scheduled
    assert Job.count() == nb_job + 1


def test_create_subdomain_in_trash(flask_client):
    user = login(flask_client)
    sl_domain = setup_sl_domain()

    subdomain = CustomDomain.create(
        domain=f"test.{sl_domain.domain}",
        user_id=user.id,
        is_sl_subdomain=True,
        commit=True,
    )

    # delete the subdomain
    CustomDomain.delete(subdomain.id)
    assert CustomDomain.get_by(domain=f"test.{sl_domain.domain}") is None

    r = flask_client.post(
        url_for("dashboard.subdomain_route"),
        data={"form-name": "create", "subdomain": "test", "domain": sl_domain.domain},
        follow_redirects=True,
    )

    assert r.status_code == 200
    assert (
        f"test.{sl_domain.domain} has been used before and cannot be reused"
        in r.data.decode()
    )


def test_create_subdomain_out_of_quota(flask_client):
    user = login(flask_client)
    sl_domain = setup_sl_domain()

    for i in range(MAX_NB_SUBDOMAIN):
        CustomDomain.create(
            domain=f"test{i}.{sl_domain.domain}",
            user_id=user.id,
            is_sl_subdomain=True,
            commit=True,
        )

    assert CustomDomain.filter_by(user_id=user.id).count() == MAX_NB_SUBDOMAIN

    flask_client.post(
        url_for("dashboard.subdomain_route"),
        data={"form-name": "create", "subdomain": "test", "domain": sl_domain.domain},
        follow_redirects=True,
    )

    # no new subdomain is created
    assert CustomDomain.filter_by(user_id=user.id).count() == MAX_NB_SUBDOMAIN


def test_create_subdomain_invalid(flask_client):
    user = login(flask_client)
    sl_domain = setup_sl_domain()

    # subdomain can't end with dash (-)
    flask_client.post(
        url_for("dashboard.subdomain_route"),
        data={"form-name": "create", "subdomain": "test-", "domain": sl_domain.domain},
        follow_redirects=True,
    )
    assert CustomDomain.filter_by(user_id=user.id).count() == 0

    # subdomain can't contain underscore (_)
    flask_client.post(
        url_for("dashboard.subdomain_route"),
        data={
            "form-name": "create",
            "subdomain": "test_test",
            "domain": sl_domain.domain,
        },
        follow_redirects=True,
    )
    assert CustomDomain.filter_by(user_id=user.id).count() == 0

    # subdomain must have at least 3 characters
    flask_client.post(
        url_for("dashboard.subdomain_route"),
        data={"form-name": "create", "subdomain": "te", "domain": sl_domain.domain},
        follow_redirects=True,
    )
    assert CustomDomain.filter_by(user_id=user.id).count() == 0
