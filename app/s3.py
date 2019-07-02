from io import BytesIO

import boto3

from app.config import AWS_REGION, BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

session = boto3.Session(
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)


def upload_from_bytesio(key: str, bs: BytesIO, content_type="string") -> None:
    bs.seek(0)
    session.resource("s3").Bucket(BUCKET).put_object(
        Key=key, Body=bs, ContentType=content_type
    )


def delete_file(key: str) -> None:
    o = session.resource("s3").Bucket(BUCKET).Object(key)
    o.delete()


def get_url(key: str) -> str:
    """by default the link will expire in 1h (3600 seconds)"""
    s3_client = session.client("s3")
    return s3_client.generate_presigned_url(
        ClientMethod="get_object", Params={"Bucket": BUCKET, "Key": key}
    )


if __name__ == "__main__":
    with open("/tmp/1.png", "rb") as f:
        upload_from_bytesio("1.png", BytesIO(f.read()))

    print(get_url(BUCKET, "1.png"))
