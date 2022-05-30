from __future__ import annotations
import base64
import email
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from mailbox import Message
from smtplib import SMTP, SMTPException
from typing import Optional, Dict, List, Callable

import newrelic.agent
from attr import dataclass

from app import config
from app.email import headers
from app.log import LOG
from app.message_utils import message_to_bytes


@dataclass
class SendRequest:
    envelope_from: str
    envelope_to: str
    msg: Message
    mail_options: Dict = {}
    rcpt_options: Dict = {}
    is_forward: bool = False
    ignore_smtp_errors: bool = False

    def to_bytes(self) -> bytes:
        if not config.SAVE_UNSENT_DIR:
            LOG.d("Skipping saving unsent message because SAVE_UNSENT_DIR is not set")
            return
        serialized_message = message_to_bytes(self.msg)
        data = {
            "envelope_from": self.envelope_from,
            "envelope_to": self.envelope_to,
            "msg": base64.b64encode(serialized_message).decode("utf-8"),
            "mail_options": self.mail_options,
            "rcpt_options": self.rcpt_options,
            "is_forward": self.is_forward,
        }
        return json.dumps(data).encode("utf-8")

    @staticmethod
    def load_from_file(file_path: str) -> SendRequest:
        with open(file_path, "rb") as fd:
            return SendRequest.load_from_bytes(fd.read())

    @staticmethod
    def load_from_bytes(data: bytes) -> SendRequest:
        decoded_data = json.loads(data)
        msg_data = base64.b64decode(decoded_data["msg"])
        msg = email.message_from_bytes(msg_data)
        return SendRequest(
            envelope_from=decoded_data["envelope_from"],
            envelope_to=decoded_data["envelope_to"],
            msg=msg,
            mail_options=decoded_data["mail_options"],
            rcpt_options=decoded_data["rcpt_options"],
            is_forward=decoded_data["is_forward"],
        )


class MailSender:
    def __init__(self):
        self._pool: Optional[ThreadPoolExecutor] = None
        self._store_emails = False
        self._emails_sent: List[SendRequest] = []

    def store_emails_instead_of_sending(self, store_emails: bool = True):
        self._store_emails = store_emails

    def purge_stored_emails(self):
        self._emails_sent = []

    def get_stored_emails(self) -> List[SendRequest]:
        return self._emails_sent

    def store_emails_test_decorator(self, fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            self.purge_stored_emails()
            self.store_emails_instead_of_sending()
            result = fn(*args, **kwargs)
            self.purge_stored_emails()
            self.store_emails_instead_of_sending(False)
            return result

        return wrapper

    def enable_background_pool(self, max_workers=10):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def send(self, send_request: SendRequest, retries: int = 2):
        """replace smtp.sendmail"""
        if self._store_emails:
            self._emails_sent.append(send_request)
        if config.NOT_SEND_EMAIL:
            LOG.d(
                "send email with subject '%s', from '%s' to '%s'",
                send_request.msg[headers.SUBJECT],
                send_request.msg[headers.FROM],
                send_request.msg[headers.TO],
            )
            return
        if not self._pool:
            self._send_to_smtp(send_request, retries)
        else:
            self._pool.submit(self._send_to_smtp, (send_request, retries))

    def _send_to_smtp(self, send_request: SendRequest, retries: int):
        try:
            start = time.time()
            if config.POSTFIX_SUBMISSION_TLS:
                smtp_port = 587
            else:
                smtp_port = config.POSTFIX_PORT

            with SMTP(config.POSTFIX_SERVER, smtp_port) as smtp:
                if config.POSTFIX_SUBMISSION_TLS:
                    smtp.starttls()

                elapsed = time.time() - start
                LOG.d("getting a smtp connection takes seconds %s", elapsed)
                newrelic.agent.record_custom_metric(
                    "Custom/smtp_connection_time", elapsed
                )

                # smtp.send_message has UnicodeEncodeError
                # encode message raw directly instead
                LOG.d(
                    "Sendmail mail_from:%s, rcpt_to:%s, header_from:%s, header_to:%s, header_cc:%s",
                    send_request.envelope_from,
                    send_request.envelope_to,
                    send_request.msg[headers.FROM],
                    send_request.msg[headers.TO],
                    send_request.msg[headers.CC],
                )
                smtp.sendmail(
                    send_request.envelope_from,
                    send_request.envelope_to,
                    message_to_bytes(send_request.msg),
                    send_request.mail_options,
                    send_request.rcpt_options,
                )

                newrelic.agent.record_custom_metric(
                    "Custom/smtp_sending_time", time.time() - start
                )
        except (
            SMTPException,
            ConnectionRefusedError,
            TimeoutError,
        ) as e:
            if retries > 0:
                time.sleep(0.3 * send_request.retries)
                self._send_to_smtp(send_request, retries - 1)
            else:
                if send_request.ignore_smtp_errors:
                    LOG.e(f"Ignore smtp error {e}")
                    return
                LOG.e(
                    f"Could not send message to smtp server {config.POSTFIX_SERVER}:{smtp_port}"
                )
                self._save_request_to_unsent_dir(send_request)

    def _save_request_to_unsent_dir(self, send_request: SendRequest):
        file_name = f"DeliveryFail-{int(time.time())}-{uuid.uuid4()}.eml"
        file_path = os.path.join(config.SAVE_UNSENT_DIR, file_name)
        file_contents = send_request.to_bytes()
        with open(file_path, "wb") as fd:
            fd.write(file_contents)
        LOG.i(f"Saved unsent message {file_path}")


mail_sender = MailSender()


def sl_sendmail(
    envelope_from: str,
    envelope_to: str,
    msg: Message,
    mail_options=(),
    rcpt_options=(),
    is_forward: bool = False,
    retries=2,
    ignore_smtp_error=False,
):
    send_request = SendRequest(
        envelope_from,
        envelope_to,
        msg,
        mail_options,
        rcpt_options,
        is_forward,
        ignore_smtp_error,
    )
    mail_sender.send(send_request, retries)
