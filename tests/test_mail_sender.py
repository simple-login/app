import os
import socket
import tempfile
import threading
from email.message import Message
from random import random
from typing import Callable

import pytest
from aiosmtpd.controller import Controller

from app import config
from app.email import headers
from app.mail_sender import (
    mail_sender,
    SendRequest,
    load_unsent_mails_from_fs_and_resend,
)


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


def compare_send_requests(expected: SendRequest, request: SendRequest):
    assert request.mail_options == expected.mail_options
    assert request.rcpt_options == expected.rcpt_options
    assert request.envelope_to == expected.envelope_to
    assert request.envelope_from == expected.envelope_from
    assert request.msg[headers.TO] == expected.msg[headers.TO]
    assert request.msg[headers.FROM] == expected.msg[headers.FROM]


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
    original_postfix_server = config.POSTFIX_SERVERS
    port_closed = closed_dummy_server()
    config.POSTFIX_SERVERS = [f"localhost:{port_closed}"]
    config.NOT_SEND_EMAIL = False
    config.POSTFIX_SUBMISSION_TLS = False
    config.POSTFIX_PORT = server_fn()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config.SAVE_UNSENT_DIR = temp_dir
            send_request = create_dummy_send_request()
            assert not mail_sender.send(send_request, 0)
            found_files = os.listdir(temp_dir)
            assert len(found_files) == 1
            loaded_send_request = SendRequest.load_from_file(
                os.path.join(temp_dir, found_files[0])
            )
            compare_send_requests(loaded_send_request, send_request)
    finally:
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


def test_mail_sender_try_several_servers():
    port_closed = closed_dummy_server()
    port_ok = smtp_response_server("250 Ok")()
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{port_closed}", f"localhost:{port_ok}"]
    config.NOT_SEND_EMAIL = False
    config.POSTFIX_SUBMISSION_TLS = False
    send_request = create_dummy_send_request()
    mail_sender._randomize_smtp_hosts = False
    try:
        assert mail_sender.send(send_request, 0)
    finally:
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


def test_mail_sender_try_backup_postfix():
    port_closed = closed_dummy_server()
    port_ok = smtp_response_server("250 Ok")()
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{port_closed}"]
    config.POSTFIX_BACKUP_SERVERS = [f"localhost:{port_ok}"]
    config.NOT_SEND_EMAIL = False
    config.POSTFIX_SUBMISSION_TLS = False
    send_request = create_dummy_send_request()
    try:
        assert mail_sender.send(send_request, 0)
    finally:
        config.POSTFIX_SERVERS = original_postfix_server
        config.POSTFIX_BACKUP_SERVERS = []
        config.NOT_SEND_EMAIL = True


@mail_sender.store_emails_test_decorator
def test_send_unsent_email_from_fs():
    original_postfix_server = config.POSTFIX_SERVERS
    port_closed = closed_dummy_server()
    config.POSTFIX_SERVERS = [f"localhost:{port_closed}"]
    config.NOT_SEND_EMAIL = False
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            config.SAVE_UNSENT_DIR = temp_dir
            send_request = create_dummy_send_request()
            assert not mail_sender.send(send_request, 1)
        finally:
            config.POSTFIX_SERVERS = original_postfix_server
            config.NOT_SEND_EMAIL = True
        saved_files = os.listdir(config.SAVE_UNSENT_DIR)
        assert len(saved_files) == 1
        mail_sender.purge_stored_emails()
        load_unsent_mails_from_fs_and_resend()
        sent_emails = mail_sender.get_stored_emails()
        assert len(sent_emails) == 1
        compare_send_requests(send_request, sent_emails[0])
        assert sent_emails[0].ignore_smtp_errors
        assert not os.path.exists(os.path.join(config.SAVE_UNSENT_DIR, saved_files[0]))
        saved_files = os.listdir(config.SAVE_UNSENT_DIR)
        assert len(saved_files) == 0


@mail_sender.store_emails_test_decorator
def test_failed_resend_does_not_delete_file():
    original_postfix_server = config.POSTFIX_SERVERS
    port_closed = closed_dummy_server()
    config.POSTFIX_SERVERS = [f"localhost:{port_closed}"]
    config.NOT_SEND_EMAIL = False
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config.SAVE_UNSENT_DIR = temp_dir
            send_request = create_dummy_send_request()
            # Send and store email in disk
            assert not mail_sender.send(send_request, 1)
            saved_files = os.listdir(config.SAVE_UNSENT_DIR)
            assert len(saved_files) == 1
            mail_sender.purge_stored_emails()
            # Send and keep email in disk
            load_unsent_mails_from_fs_and_resend()
            sent_emails = mail_sender.get_stored_emails()
            assert len(sent_emails) == 1
            compare_send_requests(send_request, sent_emails[0])
            assert sent_emails[0].ignore_smtp_errors
            assert os.path.exists(os.path.join(config.SAVE_UNSENT_DIR, saved_files[0]))
            # No more emails are stored in disk
            assert saved_files == os.listdir(config.SAVE_UNSENT_DIR)
    finally:
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


@mail_sender.store_emails_test_decorator
def test_ok_mail_does_not_generate_unsent_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        config.SAVE_UNSENT_DIR = temp_dir
        send_request = create_dummy_send_request()
        # Send and store email in disk
        assert mail_sender.send(send_request, 1)
        saved_files = os.listdir(config.SAVE_UNSENT_DIR)
        assert len(saved_files) == 0
