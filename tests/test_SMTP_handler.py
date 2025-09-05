import random
import smtplib
import pytest
import SMTP_handler
from email.message import EmailMessage
from tests.utils import create_new_user
from app.models import Alias, SMTPCredentials
from app.db import Session
from app.config import (
    EMAIL_DOMAIN,
    SMTP_INTERNAL_HOST_IP,
    SMTP_INTERNAL_PORT,
    SMTP_INTERNAL_ACCESS_SECRET
)

def test_auth_smtp_helper_success(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()

    headers = {
        "X-Secret": SMTP_INTERNAL_ACCESS_SECRET,
        "Auth-Method": "login",
        "Auth-User": valid_username,
        "Auth-Pass": valid_password,
        "Auth-Protocol": "smtp",
    }
    r= flask_client.get("/api/auth/smtp", headers=headers)

    assert r.status_code == 200
    assert r.headers["Auth-Status"] == "OK"
    assert r.headers["Auth-Server"] == SMTP_INTERNAL_HOST_IP
    assert int(r.headers["Auth-Port"]) == SMTP_INTERNAL_PORT

def test_auth_smtp_helper_failure_no_secret(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()

    headers = {
        "Auth-Method": "login",
        "Auth-User": valid_username,
        "Auth-Pass": valid_password,
        "Auth-Protocol": "smtp",
    }
    r= flask_client.get("/api/auth/smtp", headers=headers)

    assert r.status_code == 403
    assert "Auth-Status" in r.headers and r.headers["Auth-Status"] != "OK"

def test_auth_smtp_helper_failure_incomplete_headers(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()

    headers = {
        "X-Secret": SMTP_INTERNAL_ACCESS_SECRET,
        "Auth-User": valid_username,
        "Auth-Pass": valid_password,
    }
    r= flask_client.get("/api/auth/smtp", headers=headers)

    assert r.status_code == 400
    assert "Auth-Status" in r.headers and r.headers["Auth-Status"] != "OK"

def test_auth_smtp_helper_failure_wrong_user_pass(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    SMTPCredentials.create(alias_id=alias.id)
    invalid_username = "random-{}@{}".format(random.random(), EMAIL_DOMAIN)
    invalid_password = "wrong_password"
    alias.enable_SMTP = True
    Session.commit()

    headers = {
        "X-Secret": SMTP_INTERNAL_ACCESS_SECRET,
        "Auth-Method": "login",
        "Auth-User": invalid_username,
        "Auth-Pass": invalid_password,
        "Auth-Protocol": "smtp",
    }
    r= flask_client.get("/api/auth/smtp", headers=headers)

    assert r.status_code == 401
    assert "Auth-Status" in r.headers and r.headers["Auth-Status"] != "OK"

def test_auth_smtp_helper_failure_invalid_mechanism(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()

    headers = {
        "X-Secret": SMTP_INTERNAL_ACCESS_SECRET,
        "Auth-Method": "cram-md5",
        "Auth-User": valid_username,
        "Auth-Pass": valid_password,
        "Auth-Protocol": "smtp",
    }
    r= flask_client.get("/api/auth/smtp", headers=headers)

    assert r.status_code == 401
    assert "Auth-Status" in r.headers and r.headers["Auth-Status"] != "OK"

def test_auth_smtp_helper_failure_invalid_protocol(flask_client):
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()

    headers = {
        "X-Secret": SMTP_INTERNAL_ACCESS_SECRET,
        "Auth-Method": "login",
        "Auth-User": valid_username,
        "Auth-Pass": valid_password,
        "Auth-Protocol": "pop3+ssl",
    }
    r= flask_client.get("/api/auth/smtp", headers=headers)

    assert r.status_code == 401
    assert "Auth-Status" in r.headers and r.headers["Auth-Status"] != "OK"

SMTP_handler.main(SMTP_INTERNAL_HOST_IP, SMTP_INTERNAL_PORT, daemon=True)

def test_SMTP_auth_success():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    with smtplib.SMTP(SMTP_INTERNAL_HOST_IP, SMTP_INTERNAL_PORT) as server:
        response = server.login(valid_username, valid_password)
        assert response[0] == 235, f"Expected 235 for successful login, got {response[0]}"

def test_SMTP_auth_failure():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    invalid_username = "random-{}@{}".format(random.random(), EMAIL_DOMAIN)
    invalid_password = "wrong_password"
    with smtplib.SMTP(SMTP_INTERNAL_HOST_IP, SMTP_INTERNAL_PORT) as server:
        with pytest.raises(smtplib.SMTPAuthenticationError):
            server.login(invalid_username, invalid_password)


def test_SMTP_send_email_with_valid_credentials():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    msg = EmailMessage()
    msg["Subject"] = "SMTP Test"
    msg["From"] = valid_username
    msg["To"] = "random-{}@nowhere.net".format(int(random.random()))
    msg.set_content("This is a test email.")
    with smtplib.SMTP(SMTP_INTERNAL_HOST_IP, SMTP_INTERNAL_PORT) as server:
        server.login(valid_username, valid_password)
        response = server.send_message(msg)
        assert response == {}, f"Expected empty dict, indicating no errors, got {response}"

def test_SMTP_from_spoofing():
    user = create_new_user()
    alias = Alias.create_new_random(user)
    user.enable_SMTP_aliases = True
    valid_username = alias.email
    valid_password = SMTPCredentials.create(alias_id=alias.id)
    alias.enable_SMTP = True
    Session.commit()
    TO_EMAIL = "random-{}@nowhere.net".format(int(random.random()))
    SPOOFED_FROM = "random-{}@{}".format(random.random(), EMAIL_DOMAIN)
    msg = EmailMessage()
    msg["Subject"] = "From Header Spoof Test"
    msg["From"] = SPOOFED_FROM
    msg["To"] = TO_EMAIL
    msg.set_content("Testing From Spoofing.")

    with smtplib.SMTP(SMTP_INTERNAL_HOST_IP, SMTP_INTERNAL_PORT) as server:
        server.login(valid_username, valid_password)
        with pytest.raises(smtplib.SMTPResponseException):
            server.send_message(msg)
