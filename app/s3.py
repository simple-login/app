import os
from io import BytesIO
from typing import Optional

import boto3
import botocore.exceptions
import requests

from app import config
from app.log import LOG

_s3_client = None


def _get_s3client():
    global _s3_client
    if _s3_client is None:
        args = {
            "aws_access_key_id": config.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": config.AWS_SECRET_ACCESS_KEY,
            "region_name": config.AWS_REGION,
        }
        if config.AWS_ENDPOINT_URL:
            args["endpoint_url"] = config.AWS_ENDPOINT_URL
        _s3_client = boto3.client("s3", **args)
    return _s3_client


def upload_from_bytesio(key: str, bs: BytesIO, content_type="application/octet-stream"):
    bs.seek(0)

    if config.LOCAL_FILE_UPLOAD:
        file_path = os.path.join(config.UPLOAD_DIR, key)
        file_dir = os.path.dirname(file_path)
        os.makedirs(file_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(bs.read())

    else:
        _get_s3client().put_object(
            Bucket=config.BUCKET,
            Key=key,
            Body=bs,
            ContentType=content_type,
        )


def upload_email_from_bytesio(path: str, bs: BytesIO, filename):
    bs.seek(0)

    if config.LOCAL_FILE_UPLOAD:
        file_path = os.path.join(config.UPLOAD_DIR, path)
        file_dir = os.path.dirname(file_path)
        os.makedirs(file_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(bs.read())

    else:
        _get_s3client().put_object(
            Bucket=config.BUCKET,
            Key=path,
            Body=bs,
            # Support saving a remote file using Http header
            # Also supports Safari. More info at
            # https://github.com/eligrey/FileSaver.js/wiki/Saving-a-remote-file#using-http-header
            ContentDisposition=f'attachment; filename="{filename}.eml";',
        )


def download_email(path: str) -> Optional[str]:
    if config.LOCAL_FILE_UPLOAD:
        file_path = os.path.join(config.UPLOAD_DIR, path)
        with open(file_path, "rb") as f:
            return f.read()
    resp = _get_s3client().get_object(
        Bucket=config.BUCKET,
        Key=path,
    )
    if not resp or "Body" not in resp:
        return None
    return resp["Body"].read


def upload_from_url(url: str, upload_path):
    r = requests.get(url)
    upload_from_bytesio(upload_path, BytesIO(r.content))


def exists(key: str) -> bool:
    if config.LOCAL_FILE_UPLOAD:
        file_path = os.path.join(config.UPLOAD_DIR, key)
        return os.path.exists(file_path)

    try:
        _get_s3client().head_object(Bucket=config.BUCKET, Key=key)
        return True
    except botocore.exceptions.ClientError as e:
        error_code = str(e.response.get("Error", {}).get("Code", ""))
        status_code = str(
            e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", "")
        )
        if error_code in ("NoSuchKey", "NotFound", "404") or status_code == "404":
            return False
        raise


def upload_raw(
    key: str,
    bs: BytesIO,
    content_type: Optional[str] = None,
    content_disposition: Optional[str] = None,
):
    bs.seek(0)

    if config.LOCAL_FILE_UPLOAD:
        file_path = os.path.join(config.UPLOAD_DIR, key)
        file_dir = os.path.dirname(file_path)
        os.makedirs(file_dir, exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(bs.read())
    else:
        args = {
            "Bucket": config.BUCKET,
            "Key": key,
            "Body": bs,
        }
        if content_type is not None:
            args["ContentType"] = content_type
        if content_disposition is not None:
            args["ContentDisposition"] = content_disposition
        _get_s3client().put_object(**args)


def get_url(key: str, expires_in=3600) -> str:
    if config.LOCAL_FILE_UPLOAD:
        return config.URL + "/static/upload/" + key
    else:
        return _get_s3client().generate_presigned_url(
            ExpiresIn=expires_in,
            ClientMethod="get_object",
            Params={"Bucket": config.BUCKET, "Key": key},
        )


def delete(path: str):
    if config.LOCAL_FILE_UPLOAD:
        file_path = os.path.join(config.UPLOAD_DIR, path)
        os.remove(file_path)
    else:
        _get_s3client().delete_object(Bucket=config.BUCKET, Key=path)


def create_bucket_if_not_exists():
    s3client = _get_s3client()
    buckets = s3client.list_buckets()
    for bucket in buckets["Buckets"]:
        if bucket["Name"] == config.BUCKET:
            LOG.i("Bucket already exists")
            return
    s3client.create_bucket(Bucket=config.BUCKET)
    LOG.i(f"Bucket {config.BUCKET} created")
