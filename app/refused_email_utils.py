import uuid
from email.message import Message
from io import BytesIO
from typing import Optional

from app import config, s3
from app.message_utils import message_to_bytes
from app.models import RefusedEmail


def create_refused_email(
    user_id: int, message: Message, prefix: str = "refused-email"
) -> Optional[RefusedEmail]:
    refused_count = RefusedEmail.filter_by(user_id=user_id).count()
    if refused_count >= config.MAX_QUARANTINE_SIZE:
        return None
    random_name = str(uuid.uuid4())
    s3_report_path = f"refused-emails/{prefix}-{random_name}.eml"
    s3.upload_email_from_bytesio(
        s3_report_path,
        BytesIO(message_to_bytes(message)),
        f"{prefix}-{random_name}",
    )
    return RefusedEmail.create(
        full_report_path=s3_report_path, user_id=user_id, flush=True
    )
