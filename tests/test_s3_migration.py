from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import arrow
import botocore.exceptions
import pytest
import requests

from app import config
from app.db import Session
from app.models import File, RefusedEmail
from app.s3_migration import (
    MODEL_FILE,
    MODEL_REFUSED_EMAIL,
    Outcome,
    iter_keys,
    migrate_key,
)
from scripts.migrate_s3_objects import main as cli_main
from tests.utils import create_new_user, random_token

OLD_ROOT = "https://old.example.com"


@pytest.fixture(autouse=True)
def clean_db():
    """Leave no committed rows behind, like flask_client does.

    iter_keys walks the whole table, so leftover rows would leak into its
    assertions. Other tests can leave an open transaction on the shared
    connection when they return, so close the session after every test to
    release it.
    """
    try:
        yield
    finally:
        Session.remove()


@pytest.fixture
def local_upload(tmp_path):
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", True),
        patch.object(config, "UPLOAD_DIR", str(tmp_path)),
    ):
        yield tmp_path


def _response(status_code=200, content=b"data", headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = headers if headers is not None else {}
    resp.ok = 200 <= status_code < 400
    return resp


@contextmanager
def _mocked_s3():
    """Pretend the config points at an S3 bucket, with a stubbed client.

    The stub answers every HeadObject as missing, so migrate_key proceeds to
    the copy; callers inspect client.put_object for what was uploaded.
    """
    client = MagicMock()
    client.head_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "HeadObject"
    )
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", False),
        patch("app.s3._get_s3client", return_value=client),
        # s3.exists and s3.upload_raw resolve the client through the
        # module-level s3 alias of the test target
        patch("app.s3_migration.s3._get_s3client", return_value=client),
    ):
        yield client


def test_migrate_key_copies_bytes_and_headers(local_upload):
    key = "images/a b/photo.png"
    resp = _response(
        content=b"binary payload",
        headers={"Content-Type": "image/png", "Content-Disposition": "inline"},
    )

    # first pass uploads to the local dir: bytes preserved end to end
    with patch("app.s3_migration.requests.get", return_value=resp) as get:
        outcome = migrate_key(key, OLD_ROOT + "/", apply=True, timeout=10)

    assert outcome == Outcome.COPIED
    # the key is percent-encoded in the URL, the root slash is not doubled
    get.assert_called_once_with(
        "https://old.example.com/images/a%20b/photo.png", timeout=10
    )
    with open(local_upload / key, "rb") as f:
        assert f.read() == b"binary payload"

    # second pass on another key: metadata reaches the S3 API
    other_key = "images/other.png"
    with (
        _mocked_s3() as client,
        patch("app.s3_migration.requests.get", return_value=resp),
    ):
        outcome = migrate_key(other_key, OLD_ROOT, apply=True, timeout=10)

    assert outcome == Outcome.COPIED
    _, kwargs = client.put_object.call_args
    assert kwargs["Bucket"] == config.BUCKET
    assert kwargs["Key"] == other_key
    assert kwargs["ContentType"] == "image/png"
    assert kwargs["ContentDisposition"] == "inline"
    assert kwargs["Body"].read() == b"binary payload"


def test_migrate_key_returns_exists_without_get(local_upload):
    key = "already/there.bin"
    (local_upload / "already").mkdir()
    (local_upload / key).write_bytes(b"dest")

    with patch("app.s3_migration.requests.get") as get:
        outcome = migrate_key(key, OLD_ROOT, apply=True, timeout=10)

    assert outcome == Outcome.EXISTS
    get.assert_not_called()
    assert (local_upload / key).read_bytes() == b"dest"


def test_migrate_key_404_is_missing(local_upload):
    with patch("app.s3_migration.requests.get", return_value=_response(404)) as get:
        outcome = migrate_key("gone/key.bin", OLD_ROOT, apply=True, timeout=10)

    assert outcome == Outcome.MISSING
    get.assert_called_once()


def test_migrate_key_5xx_is_failed(local_upload):
    with patch("app.s3_migration.requests.get", return_value=_response(503)):
        outcome = migrate_key("bad/key.bin", OLD_ROOT, apply=True, timeout=10)

    assert outcome == Outcome.FAILED


def test_migrate_key_upload_error_is_failed(local_upload):
    client = MagicMock()
    client.head_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "HeadObject"
    )
    client.put_object.side_effect = botocore.exceptions.EndpointConnectionError(
        endpoint_url="https://s3.example.com"
    )
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", False),
        patch("app.s3._get_s3client", return_value=client),
        patch("app.s3_migration.s3._get_s3client", return_value=client),
        patch("app.s3_migration.requests.get", return_value=_response(content=b"x")),
    ):
        outcome = migrate_key("up/fail.bin", OLD_ROOT, apply=True, timeout=10)

    assert outcome == Outcome.FAILED


def test_migrate_key_timeout_is_failed(local_upload):
    with patch(
        "app.s3_migration.requests.get",
        side_effect=requests.ConnectTimeout("timed out"),
    ):
        outcome = migrate_key("slow/key.bin", OLD_ROOT, apply=True, timeout=10)

    assert outcome == Outcome.FAILED


def test_migrate_key_dry_run_uploads_nothing(local_upload):
    with patch(
        "app.s3_migration.requests.get", return_value=_response(content=b"bytes")
    ):
        outcome = migrate_key("dry/run.bin", OLD_ROOT, apply=False, timeout=10)

    assert outcome == Outcome.WOULD_COPY
    assert not (local_upload / "dry/run.bin").exists()


def test_migrate_key_eml_falls_back_to_attachment_disposition(local_upload):
    resp = _response(content=b"raw email", headers={"Content-Type": "message/rfc822"})

    with (
        _mocked_s3() as client,
        patch("app.s3_migration.requests.get", return_value=resp),
    ):
        outcome = migrate_key("provider_complaint/reply-abc.eml", OLD_ROOT, True, 10)

    assert outcome == Outcome.COPIED
    _, kwargs = client.put_object.call_args
    assert kwargs["ContentDisposition"] == 'attachment; filename="reply-abc.eml"'
    assert kwargs["ContentType"] == "message/rfc822"


def test_migrate_key_no_disposition_on_non_eml_stays_none(local_upload):
    resp = _response(content=b"x", headers={"Content-Type": "image/png"})

    with (
        _mocked_s3() as client,
        patch("app.s3_migration.requests.get", return_value=resp),
    ):
        migrate_key("images/logo.png", OLD_ROOT, True, 10)

    _, kwargs = client.put_object.call_args
    assert "ContentDisposition" not in kwargs


def _make_refused_email(user, path=None, **kwargs):
    kwargs.setdefault("full_report_path", f"fr/{random_token()}")
    return RefusedEmail.create(path=path, user_id=user.id, commit=True, **kwargs)


def test_iter_keys_covers_files_and_both_refused_email_keys(flask_client):
    user = create_new_user()
    file1 = File.create(path=f"f1/{random_token()}", commit=True)
    file2 = File.create(path=f"f2/{random_token()}", commit=True)
    re_both = _make_refused_email(
        user,
        path=f"rp/{random_token()}.eml",
        full_report_path=f"fr/full-{random_token()}.eml",
    )
    re_report_only = _make_refused_email(
        user, full_report_path=f"fr/only-{random_token()}"
    )
    expected = [
        (MODEL_FILE, file1.id, file1.path),
        (MODEL_FILE, file2.id, file2.path),
        (MODEL_REFUSED_EMAIL, re_both.id, re_both.full_report_path),
        (MODEL_REFUSED_EMAIL, re_both.id, re_both.path),
        (MODEL_REFUSED_EMAIL, re_report_only.id, re_report_only.full_report_path),
    ]

    keys = list(iter_keys(batch_size=1000))

    for entry in expected:
        assert entry in keys
    # a refused email without a path yields only its full report key
    assert (
        sum(1 for m, i, _ in keys if m == MODEL_REFUSED_EMAIL and i == re_both.id) == 2
    )
    assert (
        sum(
            1 for m, i, _ in keys if m == MODEL_REFUSED_EMAIL and i == re_report_only.id
        )
        == 1
    )


def test_iter_keys_skips_deleted_and_expiring_refused_emails(flask_client):
    user = create_new_user()
    gone_report = f"fr/deleted-{random_token()}"
    soon_report = f"fr/expiring-{random_token()}"
    _make_refused_email(
        user,
        full_report_path=gone_report,
        deleted=True,
        delete_at=arrow.now().shift(days=30),
    )
    _make_refused_email(
        user,
        full_report_path=soon_report,
        delete_at=arrow.now().shift(hours=12),
    )

    file_before = File.create(path=f"edge/{random_token()}", commit=True)
    expected_file = (MODEL_FILE, file_before.id, file_before.path)

    # the suite leaks committed rows across tests, so assert on our own keys
    # rather than on the whole table being empty
    keys = list(iter_keys(batch_size=1000))

    assert [k for k in keys if k[2] in (gone_report, soon_report)] == []
    assert expected_file in keys


def test_iter_keys_windows_cover_boundaries_and_respect_start_id_and_only(
    flask_client,
):
    paths = [f"w/{random_token()}-{i}" for i in range(5)]
    files = [File.create(path=p, commit=True) for p in paths]
    pairs = sorted((f.id, f.path) for f in files)
    ids = [i for i, _ in pairs]

    # a batch of 1 walks every id, including the first and the last
    walked = [
        (i, k) for m, i, k in iter_keys(batch_size=1, only=MODEL_FILE) if i in ids
    ]
    assert walked == pairs

    # start-id skips everything up to and including it
    middle = ids[1]
    walked = [(i, k) for m, i, k in iter_keys(1, only=MODEL_FILE, start_id=middle)]
    assert [i for i, _ in walked if i in ids] == ids[2:]

    # only=file never yields refused emails and vice versa
    user = create_new_user()
    re_ = _make_refused_email(user, full_report_path=f"fr/only-{random_token()}")
    re_id, re_report_path = re_.id, re_.full_report_path
    file_keys = list(iter_keys(1000, only=MODEL_FILE))
    assert all(m == MODEL_FILE for m, _, _ in file_keys)
    refused_keys = list(iter_keys(1000, only=MODEL_REFUSED_EMAIL))
    assert all(m == MODEL_REFUSED_EMAIL for m, _, _ in refused_keys)
    assert (MODEL_REFUSED_EMAIL, re_id, re_report_path) in refused_keys


def test_iter_keys_rejects_unknown_model(flask_client):
    with pytest.raises(ValueError):
        list(iter_keys(100, only="unknown"))


def test_iter_keys_does_not_modify_db(flask_client, local_upload):
    user = create_new_user()
    file = File.create(path=f"ro/{random_token()}", commit=True)
    re_ = _make_refused_email(
        user,
        path=f"ro/r-{random_token()}.eml",
        full_report_path=f"ro/f-{random_token()}",
    )
    re_id = re_.id
    before = {
        "file": (file.id, file.path, file.user_id),
        "refused_email": (re_.id, re_.path, re_.full_report_path, re_.deleted),
    }
    Session.expunge_all()

    list(iter_keys(1000))
    # LOCAL_FILE_UPLOAD off proves migrate_key writes nothing: with a stubbed
    # S3 client, a COPIED outcome means upload_raw was called, not the local
    # disk. start_id keeps the walk to this test's rows: rows left by other
    # test files (rolled back, lower ids) must not reach the network.
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", False),
        patch("app.s3._get_s3client", return_value=MagicMock()),
        patch("app.s3_migration.requests.get", return_value=_response(content=b"x")),
    ):
        for _, _, key in iter_keys(1000, only=MODEL_FILE, start_id=file.id - 1):
            migrate_key(key, OLD_ROOT, apply=True, timeout=10)
        for _, _, key in iter_keys(1000, only=MODEL_REFUSED_EMAIL, start_id=re_id - 1):
            migrate_key(key, OLD_ROOT, apply=True, timeout=10)

    Session.expunge_all()
    file = File.get(before["file"][0])
    re_ = RefusedEmail.get(before["refused_email"][0])
    assert (file.id, file.path, file.user_id) == before["file"]
    assert (re_.id, re_.path, re_.full_report_path, re_.deleted) == before[
        "refused_email"
    ]


def _run_cli(*argv):
    with patch("sys.argv", ["migrate_s3_objects.py", *argv]):
        return cli_main()


def test_cli_rejects_non_https_old_root(flask_client):
    assert _run_cli("--old-root", "http://old.example.com") == 1


def test_cli_refuses_to_run_with_local_file_upload(flask_client):
    with patch.object(config, "LOCAL_FILE_UPLOAD", True):
        assert _run_cli("--old-root", OLD_ROOT) == 1


def test_cli_dry_run_uploads_nothing(flask_client, local_upload):
    file = File.create(path=f"cli/{random_token()}", commit=True)
    file_path = file.path
    missing = MagicMock()
    missing.head_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "HeadObject"
    )
    # the guard needs LOCAL_FILE_UPLOAD off; start-id limits the walk to this
    # test's rows: rows left by other test files (rolled back, but with lower
    # ids) would otherwise be walked too.
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", False),
        patch("app.s3._get_s3client", return_value=missing),
        patch(
            "app.s3_migration.requests.get", return_value=_response(content=b"x")
        ) as get_mock,
    ):
        assert _run_cli("--old-root", OLD_ROOT, "--start-id", str(file.id - 1)) == 0
    assert get_mock.called
    missing.put_object.assert_not_called()
    assert not (local_upload / file_path).exists()
