import unicodedata

import bcrypt

from app.extensions import db


_NORMALIZATION_FORM = "NFKC"


class PasswordOracle:
    salt = db.Column(db.String(128), nullable=True)
    password = db.Column(db.String(128), nullable=True)

    def set_password(self, password):
        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        salt = bcrypt.gensalt()
        password_hash = bcrypt.hashpw(password.encode(), salt).decode()
        self.salt = salt.decode()
        self.password = password_hash

    def check_password(self, password) -> bool:
        if not self.password:
            return False

        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        password_hash = bcrypt.hashpw(password.encode(), self.salt.encode())
        return self.password.encode() == password_hash
