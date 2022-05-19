import time
from concurrent.futures import ThreadPoolExecutor
from mailbox import Message
from smtplib import SMTP, SMTPServerDisconnected, SMTPRecipientsRefused
from typing import Optional, Dict, List

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


class MailSender:
    def __init__(self):
        self._pool: Optional[ThreadPoolExecutor] = None
        self._store_emails = False
        self._emails_sent: List[SendRequest] = []

    def store_emails_instead_of_sending(self):
        self._store_emails = True

    def purge_stored_emails(self):
        self._emails_sent = []

    def get_stored_emails(self) -> List[SendRequest]:
        return self._emails_sent

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
        except (SMTPServerDisconnected, SMTPRecipientsRefused) as e:
            if retries > 0:
                LOG.w(
                    "SMTPServerDisconnected or SMTPRecipientsRefused error %s, retry",
                    e,
                    exc_info=True,
                )
                time.sleep(0.3 * send_request.retries)
                self._send_to_smtp(send_request, retries - 1)
            else:
                if send_request.ignore_smtp_error:
                    LOG.w("Ignore smtp error %s", e)
                else:
                    raise


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
