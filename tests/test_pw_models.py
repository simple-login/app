from hypothesis import assume, given, strategies as st
from pytest import raises
import nacl

from app.pw_models import KeyedOracle, UnkeyedOracle, XChacha20


class DummyKeyed(KeyedOracle):
    # Some abstract methods that must be implemented
    def new(self, user: int, password: bytes) -> bytes:
        raise NotImplementedError

    def check(self, user: int, password: bytes, blob: bytes) -> bool:
        raise NotImplementedError

class Keyed1(DummyKeyed): pass
class Keyed2(DummyKeyed): pass


def test_unique_keys():
    assert Keyed1().key != Keyed2().key

def test_stable_keys():
    assert Keyed1().key == Keyed1().key
    assert Keyed2().key == Keyed2().key

def test_methods_must_override():
    """Check that the methods on UnkeyedOracle must be overriden."""
    class Unkeyed(UnkeyedOracle): pass

    with raises(TypeError, match="Can't instantiate abstract class.* with abstract method"):
        Unkeyed()


class DummyUnkeyed(UnkeyedOracle):
    """A terrible, dummy implementation of an unkeyed, password-checking oracle.

    This has a host of issues, DO NOT USE.
    """

    def new(self, _user: int, password: bytes) -> bytes:
        return password

    def check(self, _user: int, password: bytes, blob: bytes) -> bool:
        return password == blob


def users():
    """Hypothesis strategy for valid user IDs."""
    return st.integers(min_value=0, max_value=2**64 - 1)


@given(user_1=users(), user_2=users(), password=st.binary())
def test_xchacha20(user_1: int, user_2: int, password: bytes):
    assume(user_1 != user_2)
    oracle = XChacha20(DummyUnkeyed(), 0)  # type: ignore
    blob = oracle.new(user_1, password)

    # Check that the password is accepted for user_1
    assert oracle.check(user_1, password, blob)
    with raises(nacl.exceptions.CryptoError):
        # Decryption fails if trying to use this record for user_2
        oracle.check(user_2, password, blob)
