import re
import secrets
import string
import time
import urllib.parse
from functools import wraps
from typing import List, Optional

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


def random_words():
    """Generate a random words. Used to generate user-facing string, for ex email addresses"""
    # nb_words = random.randint(2, 3)
    nb_words = 2
    return "_".join([secrets.choice(_words) for i in range(nb_words)])


def random_string(length=10, include_digits=False):
    """Generate a random string of fixed length"""
    letters = string.ascii_lowercase
    if include_digits:
        letters += string.digits

    return "".join(secrets.choice(letters) for _ in range(length))


def convert_to_id(s: str):
    """convert a string to id-like: remove space, remove special accent"""
    s = s.replace(" ", "")
    s = s.lower()
    s = unidecode(s)

    return s


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


def encode_url(url):
    return urllib.parse.quote(url, safe="")


def sanitize_email(email_address: str, not_lower=False) -> str:
    if email_address:
        email_address = email_address.strip().replace(" ", "").replace("\n", " ")
        if not not_lower:
            email_address = email_address.lower()
    return email_address


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
