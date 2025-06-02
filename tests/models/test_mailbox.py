from app import config
from app.dns_utils import set_global_dns_client, InMemoryDNSClient
from app.email_utils import get_email_domain_part
from app.models import Mailbox
from tests.utils import create_new_user, random_email

dns_client = InMemoryDNSClient()


def setup_module():
    set_global_dns_client(dns_client)


def teardown_module():
    set_global_dns_client(None)


def test_is_proton_with_email_domain():
    user = create_new_user()
    mailbox = Mailbox.create(
        user_id=user.id, email=f"test@{config.PROTON_EMAIL_DOMAINS[0]}"
    )
    assert mailbox.is_proton()
    mailbox = Mailbox.create(user_id=user.id, email="a@b.c")
    assert not mailbox.is_proton()


def test_is_proton_with_mx_domain():
    email = random_email()
    dns_client.set_mx_records(
        get_email_domain_part(email), {10: config.PROTON_MX_SERVERS}
    )
    user = create_new_user()
    mailbox = Mailbox.create(user_id=user.id, email=email)
    assert mailbox.is_proton()
    dns_client.set_mx_records(get_email_domain_part(email), {10: ["nowhere.net"]})
    assert not mailbox.is_proton()
