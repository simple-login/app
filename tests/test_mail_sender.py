import os
import socket
import tempfile
import threading
from email.message import Message
from random import random
from typing import Callable, List
from unittest import mock

import arrow
import pytest
from aiosmtpd.controller import Controller
from sqlalchemy.orm import sessionmaker

from app import config, s3
from app.constants import JobType
from app.db import Session, engine
from app.email import headers
from app.models import Job
from app.mail_sender import (
    mail_sender,
    SendRequest,
    load_unsent_mails_from_fs_and_resend,
)


def get_unsent_email_jobs() -> List[Job]:
    """Read through a separate connection: the job must be committed, not just
    visible in the test's transaction."""
    session = sessionmaker(bind=engine)()
    try:
        return (
            session.query(Job).filter(Job.name == JobType.SEND_UNSENT_EMAIL.value).all()
        )
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_unsent_emails():
    """Unsent-email jobs are committed in their own session, so they outlive the
    test transaction. Remove them (and their S3 objects) after each test."""
    yield
    for job in get_unsent_email_jobs():
        if s3.exists(job.payload["s3_key"]):
            s3.delete(job.payload["s3_key"])
    with engine.begin() as conn:
        conn.execute("DELETE FROM job WHERE name = %s", JobType.SEND_UNSENT_EMAIL.value)


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


@pytest.fixture
def s3_storage(monkeypatch):
    monkeypatch.setattr(config, "UNSENT_EMAIL_STORAGE", "s3")


@pytest.mark.parametrize(
    "server_fn",
    [
        close_on_connect_dummy_server,
        closed_dummy_server,
        smtp_response_server("421 Retry"),
        smtp_response_server("500 error"),
    ],
)
def test_mail_sender_save_unsent_to_s3_and_enqueue_job(server_fn, s3_storage):
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
            before = arrow.now()
            assert not mail_sender.send(send_request, 0)
            after = arrow.now()
            # Nothing is written to local disk when S3 is reachable
            assert os.listdir(temp_dir) == []
            jobs = get_unsent_email_jobs()
            assert len(jobs) == 1
            assert jobs[0].payload["attempt"] == 1
            delay = config.UNSENT_EMAIL_BACKOFF_BASE_SECS * 2
            assert before.shift(seconds=delay) <= jobs[0].run_at
            assert jobs[0].run_at <= after.shift(seconds=delay)
            key = jobs[0].payload["s3_key"]
            assert key.startswith(config.UNSENT_EMAIL_S3_PREFIX)
            compare_send_requests(
                SendRequest.load_from_bytes(s3.download_from_s3(key)), send_request
            )
    finally:
        config.SAVE_UNSENT_DIR = None
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


def test_unsent_email_job_survives_rollback_of_callers_session(s3_storage):
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{closed_dummy_server()}"]
    config.NOT_SEND_EMAIL = False
    try:
        assert not mail_sender.send(create_dummy_send_request(), 0)
        Session.rollback()
        assert len(get_unsent_email_jobs()) == 1
    finally:
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


def test_unsent_email_s3_failure_is_logged_and_dropped(s3_storage):
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{closed_dummy_server()}"]
    config.NOT_SEND_EMAIL = False
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config.SAVE_UNSENT_DIR = temp_dir
            with mock.patch.object(s3, "upload_raw", side_effect=OSError("s3 down")):
                assert not mail_sender.send(create_dummy_send_request(), 0)
            assert os.listdir(temp_dir) == []
            assert get_unsent_email_jobs() == []
    finally:
        config.SAVE_UNSENT_DIR = None
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


def test_unsent_email_fs_storage_writes_file_and_enqueues_no_job():
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{closed_dummy_server()}"]
    config.NOT_SEND_EMAIL = False
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            config.SAVE_UNSENT_DIR = temp_dir
            send_request = create_dummy_send_request()
            assert not mail_sender.send(send_request, 0)
            found_files = os.listdir(temp_dir)
            assert len(found_files) == 1
            compare_send_requests(
                SendRequest.load_from_file(os.path.join(temp_dir, found_files[0])),
                send_request,
            )
            assert get_unsent_email_jobs() == []
    finally:
        config.SAVE_UNSENT_DIR = None
        config.POSTFIX_SERVERS = original_postfix_server
        config.NOT_SEND_EMAIL = True


def test_ignore_smtp_errors_does_not_store_unsent_email():
    original_postfix_server = config.POSTFIX_SERVERS
    config.POSTFIX_SERVERS = [f"localhost:{closed_dummy_server()}"]
    config.NOT_SEND_EMAIL = False
    try:
        send_request = create_dummy_send_request()
        send_request.ignore_smtp_errors = True
        assert not mail_sender.send(send_request, 0)
        assert get_unsent_email_jobs() == []
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
    with tempfile.TemporaryDirectory() as temp_dir:
        config.SAVE_UNSENT_DIR = temp_dir
        send_request = create_dummy_send_request()
        send_request.save_request_to_unsent_dir()
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
            send_request.save_request_to_unsent_dir()
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
