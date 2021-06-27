import unicodedata

import bcrypt

from app.extensions import db

_NORMALIZATION_FORM = "NFKC"


class PasswordOracle:
    password = db.Column(db.String(128), nullable=True)

    def set_password(self, password):
        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        salt = bcrypt.gensalt()
        self.password = bcrypt.hashpw(password.encode(), salt).decode()

    def check_password(self, password) -> bool:
        if not self.password:
            return False

        password = unicodedata.normalize(_NORMALIZATION_FORM, password)
        return bcrypt.checkpw(password.encode(), self.password.encode())
