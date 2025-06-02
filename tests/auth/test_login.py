from flask import url_for

from app.db import Session
from app.utils import canonicalize_email, random_string
from tests.utils import create_new_user


def test_unactivated_user_login(flask_client):
    """
    Test function for logging in with an unactivated user.

    Steps:
    1. Creates a new user.
    2. Sets the user's activated status to False.
    3. Sends a POST request to the login route with user credentials.
    4. Checks the response status code and content for expected messages.
    """
    user = create_new_user()  # Creating a new user
    user.activated = False  # Setting the user's activated status to False
    Session.commit()  # Committing the session changes

    # Sending a POST request to the login route with user credentials and following redirects
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )

    # Asserting the response status code and content for expected messages
    assert r.status_code == 200
    assert (
        b"Please check your inbox for the activation email. You can also have this email re-sent"
        in r.data
    )


def test_non_canonical_login(flask_client):
    """
    Test function for logging in with a non-canonical email.

    Steps:
    1. Creates a new user with a non-canonical email.
    2. Sends a POST request to the login route with user credentials.
    3. Checks the response status code and content for expected messages.
    4. Checks the canonicalization of the email.
    5. Logs out the user.
    6. Sends a POST request to the login route with the canonicalized email.
    7. Checks the response status code and content for expected messages.
    """
    email = f"pre.{random_string(10)}@gmail.com"  # Generating a non-canonical email
    name = f"NAME-{random_string(10)}"  # Generating a random name
    user = create_new_user(
        email, name
    )  # Creating a new user with the generated email and name
    Session.commit()  # Committing the session changes

    # Sending a POST request to the login route with user credentials and following redirects
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": user.email, "password": "password"},
        follow_redirects=True,
    )

    # Asserting the response status code and content for expected messages
    assert r.status_code == 200
    assert name.encode("utf-8") in r.data

    # Canonicalizing the email
    canonical_email = canonicalize_email(email)
    assert (
        canonical_email != email
    )  # Checking if the canonical email is different from the original email

    flask_client.get(url_for("auth.logout"))  # Logging out the user

    # Sending a POST request to the login route with the canonicalized email and following redirects
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": canonical_email, "password": "password"},
        follow_redirects=True,
    )

    # Asserting the response status code and content for expected messages
    assert r.status_code == 200
    assert name.encode("utf-8") not in r.data


def test_canonical_login_with_non_canonical_email(flask_client):
    """
    Test function for logging in with a canonical email and a non-canonical email.

    Steps:
    1. Generates canonical and non-canonical email addresses.
    2. Creates a new user with the canonical email.
    3. Sends a POST request to the login route with the non-canonical email.
    4. Checks the response status code and content for expected messages.
    5. Logs out the user.
    6. Sends a POST request to the login route with the canonical email.
    7. Checks the response status code and content for expected messages.
    """
    suffix = f"{random_string(10)}@gmail.com"  # Generating a random suffix for emails
    canonical_email = f"pre{suffix}"  # Generating a canonical email
    non_canonical_email = f"pre.{suffix}"  # Generating a non-canonical email
    name = f"NAME-{random_string(10)}"  # Generating a random name
    create_new_user(
        canonical_email, name
    )  # Creating a new user with the canonical email
    Session.commit()  # Committing the session changes

    # Sending a POST request to the login route with the non-canonical email and following redirects
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": non_canonical_email, "password": "password"},
        follow_redirects=True,
    )

    # Asserting the response status code and content for expected messages
    assert r.status_code == 200
    assert name.encode("utf-8") in r.data

    flask_client.get(url_for("auth.logout"))  # Logging out the user

    # Sending a POST request to the login route with the canonical email and following redirects
    r = flask_client.post(
        url_for("auth.login"),
        data={"email": canonical_email, "password": "password"},
        follow_redirects=True,
    )

    # Asserting the response status code and content for expected messages
    assert r.status_code == 200
    assert name.encode("utf-8") in r.data
