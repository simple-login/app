import re
import secrets
import string
import urllib.parse
from functools import wraps
from typing import List, Optional

import time
from flask_wtf import FlaskForm
from unidecode import unidecode

from .config import WORDS_FILE_PATH, ALLOWED_REDIRECT_DOMAINS
from .log import LOG

with open(WORDS_FILE_PATH) as f:
    LOG.d("load words file: %s", WORDS_FILE_PATH)
    _words = f.read().split()


def random_word():
    return secrets.choice(_words)


def word_exist(word):
    return word in _words


def random_words(words: int = 2, numbers: int = 0):
    """Generate a random words. Used to generate user-facing string, for ex email addresses"""
    # nb_words = random.randint(2, 3)
    fields = [secrets.choice(_words) for i in range(words)]

    if numbers > 0:
        digits = [n for n in range(10)]
        suffix = "".join([str(secrets.choice(digits)) for i in range(numbers)])
        return "_".join(fields) + suffix
    else:
        return "_".join(fields)


def random_string(length=10, include_digits=False):
    """Generate a random string of fixed length"""
    letters = string.ascii_lowercase
    if include_digits:
        letters += string.digits

    return "".join(secrets.choice(letters) for _ in range(length))


_ALLOWED_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-."


def convert_to_alphanumeric(s: str) -> str:
    ret = []
    # drop all control characters like shift, separator, etc
    for c in s:
        if c not in _ALLOWED_CHARS:
            ret.append("_")
        else:
            ret.append(c)

    return "".join(ret)


def convert_to_id(s: str):
    """convert a string to id-like: remove space, remove special accent"""
    s = s.lower()
    s = unidecode(s)
    s = s.replace(" ", "")

    return convert_to_alphanumeric(s)[:64]


def encode_url(url):
    return urllib.parse.quote(url, safe="")


def canonicalize_email(email_address: str) -> str:
    email_address = sanitize_email(email_address)
    parts = email_address.split("@")
    if len(parts) != 2:
        return ""
    domain = parts[1]
    if domain not in (
        "googlemail.com",
        "gmail.com",
        "protonmail.com",
        "proton.me",
        "pm.me",
    ):
        return email_address
    first = parts[0]
    try:
        plus_idx = first.index("+")
        first = first[:plus_idx]
    except ValueError:
        # No + in the email
        pass
    first = first.replace(".", "")
    return f"{first}@{parts[1]}".lower().strip()


def sanitize_email(email_address: str, not_lower=False) -> str:
    if email_address:
        email_address = email_address.strip().replace(" ", "").replace("\n", " ")
        if not not_lower:
            email_address = email_address.lower()
    return email_address.replace("\u200f", "")


class NextUrlSanitizer:
    @staticmethod
    def sanitize(url: Optional[str], allowed_domains: List[str]) -> Optional[str]:
        if not url:
            return None
        replaced = url.replace("\\", "/")
        result = urllib.parse.urlparse(replaced)
        if result.hostname:
            if result.hostname in allowed_domains:
                return replaced
            else:
                return None
        if result.path and result.path[0] == "/" and not result.path.startswith("//"):
            if result.query:
                return f"{result.path}?{result.query}"
            return result.path

        return None


def sanitize_next_url(url: Optional[str]) -> Optional[str]:
    return NextUrlSanitizer.sanitize(url, ALLOWED_REDIRECT_DOMAINS)


def sanitize_scheme(scheme: Optional[str]) -> Optional[str]:
    if not scheme:
        return None
    if scheme in ["http", "https"]:
        return None
    scheme_regex = re.compile("^[a-z.]+$")
    if scheme_regex.match(scheme):
        return scheme
    return None


def query2str(query):
    """Useful utility method to print out a SQLAlchemy query"""
    return query.statement.compile(compile_kwargs={"literal_binds": True})


def debug_info(func):
    @wraps(func)
    def wrap(*args, **kwargs):
        start = time.time()
        LOG.d("start %s %s %s", func.__name__, args, kwargs)
        ret = func(*args, **kwargs)
        LOG.d("finish %s. Takes %s seconds", func.__name__, time.time() - start)
        return ret

    return wrap


class CSRFValidationForm(FlaskForm):
    pass
