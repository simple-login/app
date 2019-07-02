import random
import string
import urllib.parse

from unidecode import unidecode


def random_string(length=10):
    """Generate a random string of fixed length """
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for _ in range(length))


def convert_to_id(s: str):
    """convert a string to id-like: remove space, remove special accent"""
    s = s.replace(" ", "")
    s = s.lower()
    s = unidecode(s)
    return s


def encode_url(url):
    return urllib.parse.quote(url, safe="")
