"""
Verify incoming webhook from Paddle
Code inspired from https://developer.paddle.com/webhook-reference/verifying-webhooks
"""

import base64
import collections

# PHPSerialize can be found at https://pypi.python.org/pypi/phpserialize
import phpserialize
from Crypto.Hash import SHA1

# Crypto can be found at https://pypi.org/project/pycryptodome/
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5

from app.config import PADDLE_PUBLIC_KEY_PATH

# Your Paddle public key.
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
