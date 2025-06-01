import json
import os
import random
import smtplib
import ssl
import pytest
from email.message import EmailMessage

import requests
from aiosmtpd.controller import Controller

from tests.utils import create_new_user
from app.models import Alias, SMTPCredentials
from app.db import Session

import SMTP_handler

from app.config import (
    SMTP_HOST,
    SMTP_PORT,
    SMTP_INTERNAL_HOST,
    SMTP_INTERNAL_PORT,
    EMAIL_DOMAIN
)

SMTP_handler.main(SMTP_HOST, SMTP_PORT, daemon=True)

@pytest.fixture
def ssl_context():
    return ssl._create_unverified_context()

def test_implicit_ssl_connection(ssl_context):
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl_context) as server:
        code, message = server.noop()
        assert code == 250, f"Expected 250, got {code}. Message: {message.decode()}"

def test_auth_success(ssl_context):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    VALID_USERNAME = alias.email
    VALID_PASSWORD = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl_context) as server:
        response = server.login(VALID_USERNAME, VALID_PASSWORD)
        assert response[0] == 235, f"Expected 235 for successful login, got {response[0]}"

def test_auth_failure(ssl_context):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    INVALID_USERNAME = "random-{}@{}".format(random.random(), EMAIL_DOMAIN)
    INVALID_PASSWORD = "wrong_password"
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl_context) as server:
        with pytest.raises(smtplib.SMTPAuthenticationError):
            server.login(INVALID_USERNAME, INVALID_PASSWORD)


def test_send_email_with_valid_credentials(ssl_context):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    VALID_USERNAME = alias.email
    VALID_PASSWORD = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    msg = EmailMessage()
    msg["Subject"] = "SMTP Test"
    msg["From"] = VALID_USERNAME
    msg["To"] = "random-{}@nowhere.net".format(int(random.random()))
    msg.set_content("This is a test email.")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl_context) as server:
        server.login(VALID_USERNAME, VALID_PASSWORD)
        response = server.send_message(msg)
        assert response == {}, f"Expected empty dict, indicating no errors, got {response}"

def test_from_spoofing(ssl_context):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    VALID_USERNAME = alias.email
    VALID_PASSWORD = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    TO_EMAIL = "random-{}@nowhere.net".format(int(random.random()))
    SPOOFED_FROM = "random-{}@{}".format(random.random(), EMAIL_DOMAIN)
    msg = EmailMessage()
    msg["Subject"] = "From Header Spoof Test"
    msg["From"] = SPOOFED_FROM
    msg["To"] = TO_EMAIL
    msg.set_content("Testing From Spoofing.")

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl_context) as server:
        server.login(VALID_USERNAME, VALID_PASSWORD)
        with pytest.raises(smtplib.SMTPResponseException):
            server.send_message(msg)
