from __future__ import annotations

import base64
import email
import json
import os
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from functools import wraps
from smtplib import SMTP, SMTPException
from typing import Optional, Dict, List, Callable

import newrelic.agent
import sentry_sdk
import time
from attr import dataclass

from app import config
from app.email import headers
from app.log import LOG
from app.message_utils import message_to_bytes, message_format_base64_parts


@dataclass
class SendRequest:
    SAVE_EXTENSION = "sendrequest"

    envelope_from: str
    envelope_to: str
    msg: Message
    mail_options: Dict = {}
    rcpt_options: Dict = {}
    is_forward: bool = False
    ignore_smtp_errors: bool = False
    retries: int = 0

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
            "retries": self.retries,
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
            retries=decoded_data.get("retries", 1),
        )

    def save_request_to_unsent_dir(self, prefix: str = "DeliveryFail"):
        file_name = (
            f"{prefix}-{int(time.time())}-{uuid.uuid4()}.{SendRequest.SAVE_EXTENSION}"
        )
        file_path = os.path.join(config.SAVE_UNSENT_DIR, file_name)
        self.save_request_to_file(file_path)

    def save_request_to_failed_dir(self, prefix: str = "DeliveryRetryFail"):
        file_name = (
            f"{prefix}-{int(time.time())}-{uuid.uuid4()}.{SendRequest.SAVE_EXTENSION}"
        )
        dir_name = os.path.join(config.SAVE_UNSENT_DIR, "failed")
        if not os.path.isdir(dir_name):
            os.makedirs(dir_name)
        file_path = os.path.join(dir_name, file_name)
        self.save_request_to_file(file_path)

    def save_request_to_file(self, file_path: str):
        file_contents = self.to_bytes()
        with open(file_path, "wb") as fd:
            fd.write(file_contents)
        LOG.i(f"Saved unsent message {file_path}")


class MailSender:
    def __init__(self):
        self._pool: Optional[ThreadPoolExecutor] = None
        self._store_emails = False
        self._randomize_smtp_hosts = True
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

    def send(self, send_request: SendRequest, retries: int = 2) -> bool:
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
            return True
        if not self._pool:
            return self._send_to_smtp(send_request, retries)
        else:
            self._pool.submit(self._send_to_smtp, (send_request, retries))
            return True

    def _send_to_smtp(self, send_request: SendRequest, retries: int) -> bool:
        servers_to_try = config.POSTFIX_SERVERS.copy()
        if self._randomize_smtp_hosts:
            random.shuffle(servers_to_try)
        if config.POSTFIX_BACKUP_SERVERS:
            servers_to_try.extend(config.POSTFIX_BACKUP_SERVERS)
        servers_tried = 0
        for server_hostname in servers_to_try:
            servers_tried += 1
            start = time.time()
            try:
                return self.__send_to_server(server_hostname, send_request)
            except (
                SMTPException,
                ConnectionRefusedError,
                TimeoutError,
            ) as e:
                LOG.w(f"Got error {e} while sending email to {server_hostname}")
                newrelic.agent.record_custom_event("SmtpError", {"error": e.__class__})
            finally:
                newrelic.agent.record_custom_metric(
                    "Custom/smtp_servers_tried", servers_tried
                )
                newrelic.agent.record_custom_metric(
                    "Custom/smtp_sending_time", time.time() - start
                )
        if retries > 0:
            LOG.warning(
                f"Retrying sending email due to error. {retries} retries left. Will wait {0.3*retries} seconds."
            )
            time.sleep(0.3 * retries)
            return self._send_to_smtp(send_request, retries - 1)
        else:
            if send_request.ignore_smtp_errors:
                LOG.w("Ignore smtp error and skip saving to fs email")
                return False
            if config.SAVE_UNSENT_DIR:
                send_request.save_request_to_unsent_dir()
            return False

    def __send_to_server(self, server_host: str, send_request: SendRequest):
        start = time.time()
        server_split = server_host.split(":")
        if len(server_split) == 1:
            server_host = server_split[0]
            server_port = config.POSTFIX_PORT
        else:
            server_host = server_split[0]
            server_port = server_split[1]
        with SMTP(
            host=server_host, port=server_port, timeout=config.POSTFIX_CONNECT_TIMEOUT
        ) as smtp:
            smtp.sock.settimeout(config.POSTFIX_TIMEOUT)

            if config.POSTFIX_SUBMISSION_TLS:
                smtp.starttls()

            elapsed = time.time() - start
            LOG.d(
                f"Getting a smtp connection to {server_host}:{server_port} takes seconds {elapsed:.3} seconds"
            )
            newrelic.agent.record_custom_metric("Custom/smtp_connection_time", elapsed)

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
        LOG.d(
            f"Email sent using {server_host}:{server_port} from {send_request.envelope_from} to {send_request.envelope_to}"
        )
        return True


mail_sender = MailSender()


def save_request_to_failed_dir(exception_name: str, send_request: SendRequest):
    file_name = f"{exception_name}-{int(time.time())}-{uuid.uuid4()}.{SendRequest.SAVE_EXTENSION}"
    failed_file_dir = os.path.join(config.SAVE_UNSENT_DIR, "failed")
    try:
        os.makedirs(failed_file_dir)
    except FileExistsError:
        pass
    file_path = os.path.join(failed_file_dir, file_name)
    file_contents = send_request.to_bytes()
    with open(file_path, "wb") as fd:
        fd.write(file_contents)
    return file_path


def load_unsent_mails_from_fs_and_resend():
    if not config.SAVE_UNSENT_DIR:
        return
    for filename in os.listdir(config.SAVE_UNSENT_DIR):
        (_, extension) = os.path.splitext(filename)
        if extension[1:] != SendRequest.SAVE_EXTENSION:
            LOG.i(f"Skipping {filename} does not have the proper extension")
            continue
        full_file_path = os.path.join(config.SAVE_UNSENT_DIR, filename)
        if not os.path.isfile(full_file_path):
            LOG.i(f"Skipping {filename} as it's not a file")
            continue
        LOG.i(f"Trying to re-deliver email {filename}")
        try:
            send_request = SendRequest.load_from_file(full_file_path)
            send_request.retries += 1
        except Exception as e:
            LOG.e(f"Cannot load {filename}. Error {e}")
            continue
        try:
            send_request.ignore_smtp_errors = True
            if mail_sender.send(send_request, 2):
                os.unlink(full_file_path)
                newrelic.agent.record_custom_event(
                    "DeliverUnsentEmail", {"delivered": "true"}
                )
            else:
                if send_request.retries > 2:
                    os.unlink(full_file_path)
                    send_request.save_request_to_failed_dir()
                else:
                    send_request.save_request_to_file(full_file_path)
                newrelic.agent.record_custom_event(
                    "DeliverUnsentEmail", {"delivered": "false"}
                )
        except Exception as e:
            # Unlink original file to avoid re-doing the same
            os.unlink(full_file_path)
            LOG.e(
                "email sending failed with error:%s "
                "envelope %s -> %s, mail %s -> %s saved to %s",
                e,
                send_request.envelope_from,
                send_request.envelope_to,
                send_request.msg[headers.FROM],
                send_request.msg[headers.TO],
                save_request_to_failed_dir(e.__class__.__name__, send_request),
            )


@sentry_sdk.trace
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
        message_format_base64_parts(msg),
        mail_options,
        rcpt_options,
        is_forward,
        ignore_smtp_error,
    )
    mail_sender.send(send_request, retries)
