from typing import Tuple

from app.models import User, ApiKey
from tests.utils import create_new_user


def get_new_user_and_api_key() -> Tuple[User, ApiKey]:
    user = create_new_user()

    # create api_key
    api_key = ApiKey.create(user.id, "for test", commit=True)

    return user, api_key
