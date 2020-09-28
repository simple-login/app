from app.alias_utils import delete_alias
from app.extensions import db
from app.models import User, Alias, DeletedAlias


def test_delete_alias(flask_client):
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email="first@d1.test",
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )
    assert Alias.get_by(email="first@d1.test")

    delete_alias(alias, user)
    assert Alias.get_by(email="first@d1.test") is None
    assert DeletedAlias.get_by(email=alias.email)


def test_delete_alias_already_in_trash(flask_client):
    """delete an alias that's already in alias trash"""
    user = User.create(
        email="a@b.c",
        password="password",
        name="Test User",
        activated=True,
        commit=True,
    )
    alias = Alias.create(
        user_id=user.id,
        email="first@d1.test",
        mailbox_id=user.default_mailbox_id,
        commit=True,
    )

    # add the alias to global trash
    db.session.add(DeletedAlias(email=alias.email))
    db.session.commit()

    delete_alias(alias, user)
    assert Alias.get_by(email="first@d1.test") is None
