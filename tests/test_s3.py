import os
from io import BytesIO
from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

from app import config, s3


def _client_error_with_code(code: str, status_code: int = 404):
    return botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "Some Error"}},
        "HeadObject",
    )


@pytest.fixture
def local_upload(tmp_path):
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", True),
        patch.object(config, "UPLOAD_DIR", str(tmp_path)),
    ):
        yield tmp_path


@pytest.fixture
def mock_s3_client():
    client = MagicMock()
    with (
        patch.object(config, "LOCAL_FILE_UPLOAD", False),
        patch.object(s3, "_get_s3client", return_value=client),
    ):
        yield client


def test_exists_and_upload_raw_local(local_upload):
    key = "nested/dir/raw-file.bin"
    assert s3.exists(key) is False

    s3.upload_raw(key, BytesIO(b"hello world"))

    assert s3.exists(key) is True
    with open(os.path.join(str(local_upload), key), "rb") as f:
        assert f.read() == b"hello world"


def test_upload_raw_local_reads_from_start(local_upload):
    key = "raw.txt"
    bs = BytesIO(b"payload")
    bs.read()  # exhaust the stream; upload_raw must seek(0) first

    s3.upload_raw(key, bs)

    assert s3.exists(key) is True
    with open(os.path.join(str(local_upload), key), "rb") as f:
        assert f.read() == b"payload"


def test_upload_raw_s3_passes_metadata_only_when_given(mock_s3_client):
    bs = BytesIO(b"data")

    s3.upload_raw("some/key", bs)
    _, kwargs = mock_s3_client.put_object.call_args
    assert kwargs == {"Bucket": config.BUCKET, "Key": "some/key", "Body": bs}

    s3.upload_raw(
        "other/key",
        bs,
        content_type="message/rfc822",
        content_disposition='attachment; filename="a.eml"',
    )
    _, kwargs = mock_s3_client.put_object.call_args
    assert kwargs["ContentType"] == "message/rfc822"
    assert kwargs["ContentDisposition"] == 'attachment; filename="a.eml"'

    s3.upload_raw("ct/only", bs, content_type="text/plain")
    _, kwargs = mock_s3_client.put_object.call_args
    assert kwargs["ContentType"] == "text/plain"
    assert "ContentDisposition" not in kwargs


def test_exists_s3_true_when_head_object_succeeds(mock_s3_client):
    assert s3.exists("some/key") is True
    mock_s3_client.head_object.assert_called_once_with(
        Bucket=config.BUCKET, Key="some/key"
    )


@pytest.mark.parametrize("code", ["NoSuchKey", "404", "NotFound"])
def test_exists_s3_false_on_missing_key(mock_s3_client, code):
    mock_s3_client.head_object.side_effect = _client_error_with_code(code, 404)
    assert s3.exists("missing/key") is False


def test_exists_s3_reraises_other_client_errors(mock_s3_client):
    mock_s3_client.head_object.side_effect = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Forbidden"}},
        "HeadObject",
    )
    with pytest.raises(botocore.exceptions.ClientError):
        s3.exists("denied/key")
