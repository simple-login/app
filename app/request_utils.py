from random import randbytes
from base64 import b64encode


def generate_request_id() -> str:
    return b64encode(randbytes(6)).decode()
