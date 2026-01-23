from app.db import Session
from app.import_utils import import_from_csv
from app.models import (
    CustomDomain,
    Mailbox,
    Alias,
    BatchImport,
    File,
)
from tests.utils import login, random_domain, random_token
from tests.utils_test_alias import alias_export


def test_export(flask_client):
    alias_export(flask_client, "api.export_aliases")


def test_import_no_mailboxes_no_domains(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    alias_data = [
        "alias,note",
        "ebay@my-domain.com,Used on eBay",
        'facebook@my-domain.com,"Used on Facebook, Instagram."',
    ]
    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id, commit=True)

    import_from_csv(batch_import, user, alias_data)

    # Should have failed to import anything new because my-domain.com isn't registered
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # +0


def test_import_no_mailboxes(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    domain = random_domain()
    # Create domain
    CustomDomain.create(user_id=user.id, domain=domain, ownership_verified=True)
    Session.commit()

    alias_data = [
        "alias,note",
        f"ebay@{domain},Used on eBay",
        f'facebook@{domain},"Used on Facebook, Instagram."',
    ]

    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    assert len(Alias.filter_by(user_id=user.id).all()) == 3  # +2


def test_import_no_domains(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    alias_data = [
        "alias,note,mailboxes",
        "ebay@my-domain.com,Used on eBay,destination@my-destination-domain.com",
        'facebook@my-domain.com,"Used on Facebook, Instagram.",destination1@my-destination-domain.com destination2@my-destination-domain.com',
    ]

    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    # Should have failed to import anything new because my-domain.com isn't registered
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # +0


def test_import(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    domain1 = random_domain()
    domain2 = random_domain()
    # Create domains
    CustomDomain.create(user_id=user.id, domain=domain1, ownership_verified=True)
    CustomDomain.create(user_id=user.id, domain=domain2, ownership_verified=True)
    Session.commit()

    # Create mailboxes
    mailbox1 = Mailbox.create(
        user_id=user.id, email=f"destination@{domain2}", verified=True
    )
    mailbox2 = Mailbox.create(
        user_id=user.id, email=f"destination2@{domain2}", verified=True
    )
    Session.commit()

    alias_data = [
        "alias,note,mailboxes",
        f"ebay@{domain1},Used on eBay,destination@{domain2}",
        f'facebook@{domain1},"Used on Facebook, Instagram.",destination@{domain2} destination2@{domain2}',
    ]

    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    aliases = Alias.filter_by(user_id=user.id).order_by(Alias.id).all()
    assert len(aliases) == 3  # +2

    # aliases[0] is the onboarding alias, skip it

    # eBay alias
    assert aliases[1].email == f"ebay@{domain1}"
    assert len(aliases[1].mailboxes) == 1
    # First one should be primary
    assert aliases[1].mailbox_id == mailbox1.id
    # Others are sorted
    assert aliases[1].mailboxes[0] == mailbox1

    # Facebook alias
    assert aliases[2].email == f"facebook@{domain1}"
    assert len(aliases[2].mailboxes) == 2
    # First one should be primary
    assert aliases[2].mailbox_id == mailbox1.id
    # Others are sorted
    assert aliases[2].mailboxes[0] == mailbox2
    assert aliases[2].mailboxes[1] == mailbox1


def test_import_invalid_mailbox_column(flask_client):
    # Create user
    user = login(flask_client)

    # Check start state
    assert len(Alias.filter_by(user_id=user.id).all()) == 1  # Onboarding alias

    domain = random_domain()
    # Create domain
    CustomDomain.create(user_id=user.id, domain=domain, ownership_verified=True)
    Session.commit()

    alias_data = [
        "alias,note,mailboxes",
        f"ebay@{domain},Used on eBay",
        f'facebook@{domain},"Used on Facebook, Instagram."',
    ]

    file = File.create(path=f"/{random_token()}", commit=True)
    batch_import = BatchImport.create(user_id=user.id, file_id=file.id)

    import_from_csv(batch_import, user, alias_data)

    assert len(Alias.filter_by(user_id=user.id).all()) == 3  # +2
