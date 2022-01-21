from app import auth_utils


def test_check_pwnedpasswords():
    assert auth_utils.check_pwnedpasswords("password") is True
