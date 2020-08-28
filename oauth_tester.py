"""
This is an example on how to integrate SimpleLogin
with Requests-OAuthlib, a popular library to work with OAuth in Python.
The step-to-step guide can be found on https://docs.simplelogin.io
This example is based on
https://requests-oauthlib.readthedocs.io/en/latest/examples/real_world_example.html
"""
import os

from flask import Flask, request, redirect, session, url_for
from flask.json import jsonify
from requests_oauthlib import OAuth2Session

app = Flask(__name__)

# this demo uses flask.session that requires the `secret_key` to be set
app.secret_key = "very secret"

# "prettify" the returned json in /profile
app.config["JSONIFY_PRETTYPRINT_REGULAR"] = True

# This client credential is obtained upon registration of a new SimpleLogin App on
# https://app.simplelogin.io/developer/new_client
# Please make sure to export these credentials to env variables:
# export CLIENT_ID={your_client_id}
# export CLIENT_SECRET={your_client_secret}
client_id = os.environ.get("CLIENT_ID") or "client-id"
client_secret = os.environ.get("CLIENT_SECRET") or "client-secret"

# SimpleLogin urls
authorization_base_url = "http://localhost:7777/oauth2/authorize"
token_url = "http://localhost:7777/oauth2/token"
userinfo_url = "http://localhost:7777/oauth2/userinfo"


@app.route("/")
def demo():
    """Step 1: User Authorization.
    Redirect the user/resource owner to the OAuth provider (i.e. SimpleLogin)
    using an URL with a few key OAuth parameters.
    """
    simplelogin = OAuth2Session(
        client_id, redirect_uri="http://127.0.0.1:5000/callback"
    )
    authorization_url, state = simplelogin.authorization_url(authorization_base_url)

    # State is used to prevent CSRF, keep this for later.
    session["oauth_state"] = state
    return redirect(authorization_url)


# Step 2: User authorization, this happens on the provider.


@app.route("/callback", methods=["GET"])
def callback():
    """Step 3: Retrieving an access token.
    The user has been redirected back from the provider to your registered
    callback URL. With this redirection comes an authorization code included
    in the redirect URL. We will use that to obtain an access token.
    """

    simplelogin = OAuth2Session(client_id, state=session["oauth_state"])
    token = simplelogin.fetch_token(
        token_url, client_secret=client_secret, authorization_response=request.url
    )

    # At this point you can fetch protected resources but lets save
    # the token and show how this is done from a persisted token
    # in /profile.
    session["oauth_token"] = token

    return redirect(url_for(".profile"))


@app.route("/profile", methods=["GET"])
def profile():
    """Fetching a protected resource using an OAuth 2 token."""
    simplelogin = OAuth2Session(client_id, token=session["oauth_token"])
    return jsonify(simplelogin.get(userinfo_url).json())


# This allows us to use a plain HTTP callback
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

if __name__ == "__main__":
    app.secret_key = os.urandom(24)
    app.run(debug=True)
