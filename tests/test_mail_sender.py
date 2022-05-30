import os
import tempfile
import threading
import socket
from email.message import Message
from random import random
from typing import Callable

import pytest
from aiosmtpd.controller import Controller

from app.email import headers
from app.mail_sender import mail_sender, SendRequest
from app import config


def create_dummy_send_request() -> SendRequest:
    to_addr = f"to-{int(random())}@destination.com"
    from_addr = f"from-{int(random())}@source.com"
    msg = Message()
    msg[headers.TO] = to_addr
    msg[headers.FROM] = from_addr
    msg[headers.SUBJECT] = f"Random subject {random()}"
    msg.set_payload(f"Test content {random()}")

    return SendRequest(
        f"from-{int(random())}@envelope.com",
        to_addr,
        msg,
    )


@mail_sender.store_emails_test_decorator
def test_mail_sender_save_to_mem():
    send_request = create_dummy_send_request()
    mail_sender.send(send_request, 0)
    stored_emails = mail_sender.get_stored_emails()
    assert len(stored_emails) == 1
    assert stored_emails[0] == send_request


def close_on_connect_dummy_server() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("localhost", 0))
    sock.listen()
    port = sock.getsockname()[1]

    def close_on_accept():
        connection, _ = sock.accept()
        connection.close()
        sock.close()

    threading.Thread(target=close_on_accept, daemon=True).start()
    return port


def closed_dummy_server() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("localhost", 0))
    sock.listen()
    port = sock.getsockname()[1]
    sock.close()
    return port


def smtp_response_server(smtp_response: str) -> Callable[[], int]:
    def inner():
        empty_port = closed_dummy_server()

        class ResponseHandler:
            async def handle_DATA(self, server, session, envelope) -> str:
                return smtp_response

        controller = Controller(
            ResponseHandler(), hostname="localhost", port=empty_port
        )
        controller.start()
        return controller.server.sockets[0].getsockname()[1]

    return inner


@pytest.mark.parametrize(
    "server_fn",
    [
        close_on_connect_dummy_server,
        closed_dummy_server,
        smtp_response_server("421 Retry"),
        smtp_response_server("500 error"),
    ],
)
def test_mail_sender_save_unsent_to_disk(server_fn):
    original_postfix_server = config.POSTFIX_SERVER
    config.POSTFIX_SERVER = "localhost"
    config.NOT_SEND_EMAIL = False
    config.POSTFIX_SUBMISSION_TLS = False
    config.POSTFIX_PORT = server_fn()
    with tempfile.TemporaryDirectory() as temp_dir:
        config.SAVE_UNSENT_DIR = temp_dir
        send_request = create_dummy_send_request()
        mail_sender.send(send_request, 0)
        found_files = os.listdir(temp_dir)
        assert len(found_files) == 1
        loaded_send_request = SendRequest.load_from_file(
            os.path.join(temp_dir, found_files[0])
        )
        assert send_request.mail_options == loaded_send_request.mail_options
        assert send_request.rcpt_options == loaded_send_request.rcpt_options
        assert send_request.envelope_to == loaded_send_request.envelope_to
        assert send_request.envelope_from == loaded_send_request.envelope_from
        assert send_request.msg[headers.TO] == loaded_send_request.msg[headers.TO]
        assert send_request.msg[headers.FROM] == loaded_send_request.msg[headers.FROM]
    config.POSTFIX_SERVER = original_postfix_server
    config.NOT_SEND_EMAIL = True
