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
    AWS_ENDPOINT_URL,
)
from app.log import LOG


_s3_client = None


def _get_s3client():
    global _s3_client
    if _s3_client is None:
        args = {
            "aws_access_key_id": AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": AWS_SECRET_ACCESS_KEY,
            "region_name": AWS_REGION,
        }
        if AWS_ENDPOINT_URL:
            args["endpoint_url"] = AWS_ENDPOINT_URL
        _s3_client = boto3.client("s3", **args)
    return _s3_client


def upload_from_bytesio(key: str, bs: BytesIO, content_type="application/octet-stream"):
    bs.seek(0)

    if LOCAL_FILE_UPLOAD:
        file_path = os.path.join(UPLOAD_DIR, key)
        file_dir = os.path.dirname(file_path)
        os.makedirs(file_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(bs.read())

    else:
        _get_s3client().put_object(
            Bucket=BUCKET,
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
        _get_s3client().put_object(
            Bucket=BUCKET,
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
    resp = _get_s3client().get_object(
        Bucket=BUCKET,
        Key=path,
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
        return _get_s3client().generate_presigned_url(
            ExpiresIn=expires_in,
            ClientMethod="get_object",
            Params={"Bucket": BUCKET, "Key": key},
        )


def delete(path: str):
    if LOCAL_FILE_UPLOAD:
        os.remove(os.path.join(UPLOAD_DIR, path))
    else:
        _get_s3client().delete_object(Bucket=BUCKET, Key=path)


def create_bucket_if_not_exists():
    s3client = _get_s3client()
    buckets = s3client.list_buckets()
    for bucket in buckets["Buckets"]:
        if bucket["Name"] == BUCKET:
            LOG.i("Bucket already exists")
            return
    s3client.create_bucket(Bucket=BUCKET)
    LOG.i(f"Bucket {BUCKET} created")
