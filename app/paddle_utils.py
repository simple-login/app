"""
Verify incoming webhook from Paddle
Code inspired from https://developer.paddle.com/webhook-reference/verifying-webhooks
"""

import base64
import collections

# PHPSerialize can be found at https://pypi.python.org/pypi/phpserialize
import phpserialize
import requests
from Crypto.Hash import SHA1

# Crypto can be found at https://pypi.org/project/pycryptodome/
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5

from app.config import PADDLE_PUBLIC_KEY_PATH, PADDLE_VENDOR_ID, PADDLE_AUTH_CODE

# Your Paddle public key.
from app.log import LOG
from app.models import User

with open(PADDLE_PUBLIC_KEY_PATH) as f:
    public_key = f.read()


# Convert key from PEM to DER - Strip the first and last lines and newlines, and decode
public_key_encoded = public_key[26:-25].replace("\n", "")
public_key_der = base64.b64decode(public_key_encoded)


def verify_incoming_request(form_data: dict) -> bool:
    """verify the incoming form_data"""
    # copy form data
    input_data = form_data.copy()

    signature = input_data["p_signature"]

    # Remove the p_signature parameter
    del input_data["p_signature"]

    # Ensure all the data fields are strings
    for field in input_data:
        input_data[field] = str(input_data[field])

    # Sort the data
    sorted_data = collections.OrderedDict(sorted(input_data.items()))

    # and serialize the fields
    serialized_data = phpserialize.dumps(sorted_data)

    # verify the data
    key = RSA.importKey(public_key_der)
    digest = SHA1.new()
    digest.update(serialized_data)
    verifier = PKCS1_v1_5.new(key)
    signature = base64.b64decode(signature)
    if verifier.verify(digest, signature):
        return True
    return False


def cancel_subscription(subscription_id: str) -> bool:
    r = requests.post(
        "https://vendors.paddle.com/api/2.0/subscription/users_cancel",
        data={
            "vendor_id": PADDLE_VENDOR_ID,
            "vendor_auth_code": PADDLE_AUTH_CODE,
            "subscription_id": subscription_id,
        },
    )
    res = r.json()
    if not res["success"]:
        LOG.e(f"cannot cancel subscription {subscription_id}, paddle response: {res}")

    return res["success"]


def change_plan(user: User, subscription_id: str, plan_id) -> (bool, str):
    """return whether the operation is successful and an optional error message"""
    r = requests.post(
        "https://vendors.paddle.com/api/2.0/subscription/users/update",
        data={
            "vendor_id": PADDLE_VENDOR_ID,
            "vendor_auth_code": PADDLE_AUTH_CODE,
            "subscription_id": subscription_id,
            "plan_id": plan_id,
        },
    )
    res = r.json()
    if not res["success"]:
        try:
            # "unable to complete the resubscription because we could not charge the customer for the resubscription"
            if res["error"]["code"] == 147:
                LOG.w(
                    "could not charge the customer for the resubscription error %s,%s",
                    subscription_id,
                    user,
                )
                return False, "Your card cannot be charged"
        except KeyError:
            LOG.e(
                f"cannot change subscription {subscription_id} to {plan_id}, paddle response: {res}"
            )
            return False, ""

        return False, ""

    return res["success"], ""
