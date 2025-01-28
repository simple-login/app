def generate_request_id() -> str:
    from random import randbytes
    from base64 import b64encode

    return b64encode(randbytes(6)).decode()
