from abc import ABC, abstractmethod
from enum import IntEnum, unique
from functools import lru_cache
from hashlib import blake2b
import unicodedata

import bcrypt
from nacl.secret import Aead
from sqlalchemy_utils import ChoiceType

from app.config import PW_SITE_KEY
from app.extensions import db

_NORMALIZATION_FORM = "NFKC"


class UnkeyedOracle(ABC):
    """Abstract Base Class for unkeyed password oracles, such as bcrypt.

    Such unkeyed constructions should only ever be used through a wrapper
    that turns them into a keyed oracle, such as XChacha20.
    """

    @abstractmethod
    def new(self, user: int, password: bytes) -> bytes:
        pass

    @abstractmethod
    def check(self, user: int, password: bytes, blob: bytes) -> bool:
        pass


class KeyedOracle(UnkeyedOracle):
    "Helper class that derives a class-specific key, from the site-wide key."

    # Prepare the necessary Blake2b state when the class is initialized
    _KEY_HASHER = blake2b(
        key=PW_SITE_KEY,
        person=blake2b(
            b"simplelogin.io/pw_models/KeyedOracle", digest_size=blake2b.PERSON_SIZE
        ).digest(),
        digest_size=32,
    )

    "32 bytes secret key, unique to the subclass."

    @property
    def key(self):
        # Using Blake2 as a fast KDF
        return (
            KeyedOracle._KEY_HASHER.copy()
            .update(
                type(self).__name__.encode("ASCII"),
            )
            .digest()
        )


class Bcrypt(UnkeyedOracle):
    # See https://docs.python.org/3/reference/datamodel.html#slots
    __slots__ = tuple()

    def new(self, _user: int, password: bytes) -> bytes:
        return bcrypt.hashpw(password, bcrypt.gensalt())

    def check(self, _user: int, password: bytes, blob: bytes) -> bool:
        return bcrypt.checkpw(password, blob)


class XChacha20(KeyedOracle):
    __slots__ = ("box", "kind_id", "oracle")
    box: Aead
    oracle: UnkeyedOracle
    kind_id: bytes

    def __init__(self, oracle: UnkeyedOracle, kind: "PasswordKind"):
        self.box = Aead(self.key)
        self.oracle = oracle
        self.kind_id = kind.to_bytes(8, byteorder="big")

    def aad(self, user: int) -> bytes:
        # Construct an AAD value, binding the (encrypted) password hash to
        # a specific (PasswordKind, user) pair.
        # This prevents an attacker with read/write access to the DB but no
        # knowledge of the secret key, from changing a user's password entry.
        #
        # Using plain concatenation is safe, as the components are both
        # fixed-size byte strings.  Endianness is fixed, so the AADs stay
        # stable across various architectures; network order is conventional.
        return self.kind_id + user.to_bytes(8, byteorder="big")

    def new(self, user: int, password: bytes) -> bytes:
        return self.box.encrypt(
            self.oracle.new(user, password),
            self.aad(user),
        )

    def check(self, user: int, password: bytes, blob: bytes) -> bool:
        return self.oracle.check(
            user,
            password,
            self.box.decrypt(
                blob,
                self.aad(user),
            ),
        )


@unique
class PasswordKind(IntEnum):
    AEAD_XCHACHA20_BCRYPT = 0

    @property
    @lru_cache(1)
    def oracle(self) -> KeyedOracle:
        if self == PasswordKind.AEAD_XCHACHA20_BCRYPT:
            return XChacha20(Bcrypt(), self)
        else:
            raise ValueError(f"Unexpected PasswordKind: '{self!r}'")


DEFAULT_KIND = PasswordKind.AEAD_XCHACHA20_BCRYPT


class PasswordOracle:
    pw_blob = db.Column(db.BINARY, nullable=True)
    pw_kind = db.Column(ChoiceType(PasswordKind), nullable=True)

    def set_password(self, password):
        if self.id is None:
            print(self)
        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        self.pw_kind = DEFAULT_KIND
        self.pw_blob = DEFAULT_KIND.oracle.new(self.id, password.encode())

    def check_password(self, password) -> bool:
        if not (self.pw_blob and self.pw_kind):
            return False

        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        return self.pw_kind.oracle.check(self.id, password.encode(), self.pw_blob)
