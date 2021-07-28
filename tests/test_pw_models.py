from pytest import raises

from app.pw_models import KeyedOracle


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

