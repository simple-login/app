import bcrypt
import sqlalchemy as sa
import unicodedata

_NORMALIZATION_FORM = "NFKC"
# bcrypt cost factor. Tests lower it (see tests/conftest.py) since hashing at
# the default cost takes ~200ms and dominates the test suite runtime.
BCRYPT_ROUNDS = 12


class PasswordOracle:
    password = sa.Column(sa.String(128), nullable=True)

    def set_password(self, password):
        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
        self.password = bcrypt.hashpw(password.encode(), salt).decode()

    def check_password(self, password) -> bool:
        if not self.password:
            return False

        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        return bcrypt.checkpw(password.encode(), self.password.encode())
