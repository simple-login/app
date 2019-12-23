from io import BytesIO

import boto3
import requests

from app.config import AWS_REGION, BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

_session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)


def upload_from_bytesio(key: str, bs: BytesIO, content_type="string") -> None:
    bs.seek(0)
    _session.resource("s3").Bucket(BUCKET).put_object(
        Key=key, Body=bs, ContentType=content_type
    )


def upload_from_url(url: str, upload_path):
    r = requests.get(url)
    upload_from_bytesio(upload_path, BytesIO(r.content))


def delete_file(key: str) -> None:
    o = _session.resource("s3").Bucket(BUCKET).Object(key)
    o.delete()


def get_url(key: str, expires_in=3600) -> str:
    s3_client = _session.client("s3")
    return s3_client.generate_presigned_url(
        ExpiresIn=expires_in,
        ClientMethod="get_object",
        Params={"Bucket": BUCKET, "Key": key},
    )
