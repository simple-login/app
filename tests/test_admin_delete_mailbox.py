import pytest

from app import config
from app.constants import JobType
from app.db import Session
from app.mailbox_utils import MailboxError, admin_delete_mailbox, delete_mailbox
from app.models import (
    AdminAuditLog,
    Alias,
    AuditLogActionEnum,
    Job,
    JobState,
    Mailbox,
)
from job_runner import delete_mailbox_job
from tests.utils import create_new_user, random_email


def setup_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = True


def teardown_module():
    config.SKIP_MX_LOOKUP_ON_CHECK = False


def _mailbox(user, verified=True) -> Mailbox:
    return Mailbox.create(
        user_id=user.id, email=random_email(), verified=verified, commit=True
    )


def _delete_jobs() -> list[Job]:
    return Session.query(Job).filter(Job.name == JobType.DELETE_MAILBOX.value).all()


def _queued(user, mailbox, target, state=JobState.ready):
    delete_mailbox(user, mailbox.id, target.id, send_mail=False)
    job = max(_delete_jobs(), key=lambda j: j.id)
    job.state = state.value
    Session.commit()
    return job


def _admin():
    return create_new_user()


def test_delete_non_default_mailbox_targets_default():
    user = create_new_user()
    other = _mailbox(user)
    default_id = user.default_mailbox_id

    target = admin_delete_mailbox(other, _admin())

    assert target.id == default_id
    job = max(_delete_jobs(), key=lambda j: j.id)
    assert job.payload["mailbox_id"] == other.id
    assert job.payload["transfer_mailbox_id"] == default_id
    assert job.payload["send_mail"] is False
    log = (
        Session.query(AdminAuditLog)
        .filter_by(model_id=user.id, action=AuditLogActionEnum.delete_mailbox.value)
        .first()
    )
    assert log is not None


def test_delete_default_mailbox_promotes_oldest_eligible():
    user = create_new_user()
    old_default_id = user.default_mailbox_id
    unverified = _mailbox(user, verified=False)
    first = _mailbox(user)
    _mailbox(user)

    target = admin_delete_mailbox(Mailbox.get(old_default_id), _admin())

    assert target.id == first.id != unverified.id
    assert user.default_mailbox_id == first.id
    job = max(_delete_jobs(), key=lambda j: j.id)
    assert job.payload["transfer_mailbox_id"] == first.id
    actions = {
        a.action for a in Session.query(AdminAuditLog).filter_by(model_id=user.id)
    }
    assert AuditLogActionEnum.change_default_mailbox.value in actions
    assert AuditLogActionEnum.delete_mailbox.value in actions


def test_delete_default_without_replacement_and_aliases_has_no_target():
    user = create_new_user()
    default = Mailbox.get(user.default_mailbox_id)
    for alias in default.aliases:
        Session.delete(alias)
    Session.commit()

    target = admin_delete_mailbox(default, _admin())

    assert target is None
    assert user.default_mailbox_id is None
    assert (
        max(_delete_jobs(), key=lambda j: j.id).payload["transfer_mailbox_id"] is None
    )


def test_delete_default_without_replacement_with_aliases_refused():
    user = create_new_user()
    default = Mailbox.get(user.default_mailbox_id)
    Alias.create_new_random(user)
    Session.commit()
    before = len(_delete_jobs())
    with pytest.raises(MailboxError):
        admin_delete_mailbox(default, _admin())
    assert len(_delete_jobs()) == before
    assert user.default_mailbox_id == default.id


def test_admin_disabled_mailbox_can_be_deleted():
    user = create_new_user()
    other = _mailbox(user)
    other.flags = other.flags | Mailbox.FLAG_ADMIN_DISABLED
    Session.commit()
    target = admin_delete_mailbox(other, _admin())
    assert target.id == user.default_mailbox_id


def test_job_moves_aliases_to_new_default():
    user = create_new_user()
    default = Mailbox.get(user.default_mailbox_id)
    other = _mailbox(user)
    alias = Alias.create_new_random(user)
    alias.mailbox_id = default.id
    Session.commit()

    admin_delete_mailbox(default, _admin())
    delete_mailbox_job(max(_delete_jobs(), key=lambda j: j.id))

    assert Mailbox.get(default.id) is None
    assert Alias.get(alias.id).mailbox_id == other.id


@pytest.mark.parametrize("state", [JobState.ready, JobState.taken])
def test_review_sequence_delete_b_then_default_a_refused(state):
    user = create_new_user()
    a = Mailbox.get(user.default_mailbox_id)
    b = _mailbox(user)
    admin_delete_mailbox(b, _admin())
    job = max(_delete_jobs(), key=lambda j: j.id)
    job.state = state.value
    Session.commit()
    before = len(_delete_jobs())

    with pytest.raises(MailboxError):
        admin_delete_mailbox(a, _admin())

    assert user.default_mailbox_id == a.id
    assert len(_delete_jobs()) == before


@pytest.mark.parametrize("state", [JobState.ready, JobState.taken])
def test_pending_mailbox_skipped_when_choosing_default(state):
    user = create_new_user()
    a = Mailbox.get(user.default_mailbox_id)
    b = _mailbox(user)
    c = _mailbox(user)
    _queued(user, b, c, state)

    target = admin_delete_mailbox(a, _admin())

    assert target.id == c.id
    assert user.default_mailbox_id == c.id


@pytest.mark.parametrize("state", [JobState.ready, JobState.taken])
def test_mailbox_already_pending_refused(state):
    user = create_new_user()
    b = _mailbox(user)
    _queued(user, b, Mailbox.get(user.default_mailbox_id), state)
    before = len(_delete_jobs())
    with pytest.raises(MailboxError):
        admin_delete_mailbox(b, _admin())
    assert len(_delete_jobs()) == before


@pytest.mark.parametrize("state", [JobState.ready, JobState.taken])
def test_pending_transfer_target_cannot_be_deleted(state):
    user = create_new_user()
    b = _mailbox(user)
    c = _mailbox(user)
    _queued(user, b, c, state)
    before = len(_delete_jobs())
    with pytest.raises(MailboxError):
        admin_delete_mailbox(c, _admin())
    assert len(_delete_jobs()) == before


def test_done_jobs_are_ignored():
    user = create_new_user()
    a = Mailbox.get(user.default_mailbox_id)
    b = _mailbox(user)
    _queued(user, b, a, JobState.done)

    target = admin_delete_mailbox(a, _admin())

    assert target.id == b.id


def test_delete_after_default_cleared_does_not_crash():
    user = create_new_user()
    a = Mailbox.get(user.default_mailbox_id)
    for alias in a.aliases:
        Session.delete(alias)
    b = _mailbox(user, verified=False)
    Session.commit()

    assert admin_delete_mailbox(a, _admin()) is None
    assert user.default_mailbox_id is None

    assert admin_delete_mailbox(b, _admin()) is None
    assert max(_delete_jobs(), key=lambda j: j.id).payload["mailbox_id"] == b.id


def test_delete_with_aliases_and_no_default_refused():
    user = create_new_user()
    b = _mailbox(user, verified=False)
    alias = Alias.create_new_random(user)
    alias.mailbox_id = b.id
    user.default_mailbox_id = None
    Session.commit()
    before = len(_delete_jobs())
    with pytest.raises(MailboxError):
        admin_delete_mailbox(b, _admin())
    assert len(_delete_jobs()) == before
