import os
from io import BytesIO
from typing import Optional

import boto3
import requests

from app.config import (
    AWS_REGION,
    BUCKET,
    AWS_ACCESS_KEY_ID,
    AWS_SECRET_ACCESS_KEY,
    LOCAL_FILE_UPLOAD,
    UPLOAD_DIR,
    URL,
)

if not LOCAL_FILE_UPLOAD:
    _session = boto3.Session(
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        region_name=AWS_REGION,
    )


def upload_from_bytesio(key: str, bs: BytesIO, content_type="string"):
    bs.seek(0)

    if LOCAL_FILE_UPLOAD:
        file_path = os.path.join(UPLOAD_DIR, key)
        file_dir = os.path.dirname(file_path)
        os.makedirs(file_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(bs.read())

    else:
        _session.resource("s3").Bucket(BUCKET).put_object(
            Key=key,
            Body=bs,
            ContentType=content_type,
        )


def upload_email_from_bytesio(path: str, bs: BytesIO, filename):
    bs.seek(0)

    if LOCAL_FILE_UPLOAD:
        file_path = os.path.join(UPLOAD_DIR, path)
        file_dir = os.path.dirname(file_path)
        os.makedirs(file_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(bs.read())

    else:
        _session.resource("s3").Bucket(BUCKET).put_object(
            Key=path,
            Body=bs,
            # Support saving a remote file using Http header
            # Also supports Safari. More info at
            # https://github.com/eligrey/FileSaver.js/wiki/Saving-a-remote-file#using-http-header
            ContentDisposition=f'attachment; filename="{filename}.eml";',
        )


def download_email(path: str) -> Optional[str]:
    if LOCAL_FILE_UPLOAD:
        file_path = os.path.join(UPLOAD_DIR, path)
        with open(file_path, "rb") as f:
            return f.read()
    resp = (
        _session.resource("s3")
        .Bucket(BUCKET)
        .get_object(
            Key=path,
        )
    )
    if not resp or "Body" not in resp:
        return None
    return resp["Body"].read


def upload_from_url(url: str, upload_path):
    r = requests.get(url)
    upload_from_bytesio(upload_path, BytesIO(r.content))


def get_url(key: str, expires_in=3600) -> str:
    if LOCAL_FILE_UPLOAD:
        return URL + "/static/upload/" + key
    else:
        s3_client = _session.client("s3")
        return s3_client.generate_presigned_url(
            ExpiresIn=expires_in,
            ClientMethod="get_object",
            Params={"Bucket": BUCKET, "Key": key},
        )


def delete(path: str):
    if LOCAL_FILE_UPLOAD:
        os.remove(os.path.join(UPLOAD_DIR, path))
    else:
        o = _session.resource("s3").Bucket(BUCKET).Object(path)
        o.delete()
