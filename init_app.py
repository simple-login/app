from app.config import (
    ALIAS_DOMAINS,
    PREMIUM_ALIAS_DOMAINS,
    get_abs_path,
    DISPOSABLE_FILE_PATH,
)
from app.db import Session
from app.log import LOG
from app.models import Mailbox, Contact, SLDomain, InvalidMailboxDomain
from app.pgp_utils import load_public_key
from server import create_light_app


def load_pgp_public_keys():
    """Load PGP public key to keyring"""
    for mailbox in Mailbox.filter(Mailbox.pgp_public_key.isnot(None)).all():
        LOG.d("Load PGP key for mailbox %s", mailbox)
        fingerprint = load_public_key(mailbox.pgp_public_key)

        # sanity check
        if fingerprint != mailbox.pgp_finger_print:
            LOG.e("fingerprint %s different for mailbox %s", fingerprint, mailbox)
            mailbox.pgp_finger_print = fingerprint
    Session.commit()

    for contact in Contact.filter(Contact.pgp_public_key.isnot(None)).all():
        LOG.d("Load PGP key for %s", contact)
        fingerprint = load_public_key(contact.pgp_public_key)

        # sanity check
        if fingerprint != contact.pgp_finger_print:
            LOG.e("fingerprint %s different for contact %s", fingerprint, contact)
            contact.pgp_finger_print = fingerprint

    Session.commit()

    LOG.d("Finish load_pgp_public_keys")


def add_sl_domains():
    for alias_domain in ALIAS_DOMAINS:
        if SLDomain.get_by(domain=alias_domain):
            LOG.d("%s is already a SL domain", alias_domain)
        else:
            LOG.i("Add %s to SL domain", alias_domain)
            SLDomain.create(domain=alias_domain)

    for premium_domain in PREMIUM_ALIAS_DOMAINS:
        if SLDomain.get_by(domain=premium_domain):
            LOG.d("%s is already a SL domain", premium_domain)
        else:
            LOG.i("Add %s to SL domain", premium_domain)
            SLDomain.create(domain=premium_domain, premium_only=True)

    Session.commit()


def add_invalid_mailbox_domains():
    with open(get_abs_path(DISPOSABLE_FILE_PATH), "r") as f:
        disposable_email_domains = f.readlines()
        disposable_email_domains = [d.strip().lower() for d in disposable_email_domains]
        disposable_email_domains = [
            d for d in disposable_email_domains if not d.startswith("#")
        ]

        for domain in disposable_email_domains:
            if InvalidMailboxDomain.get_by(domain=domain) is None:
                LOG.i("Add disposable domain %s as invalid mailbox domain", domain)
                InvalidMailboxDomain.create(domain=domain)

        Session.commit()


if __name__ == "__main__":
    # wrap in an app context to benefit from app setup like database cleanup, sentry integration, etc
    with create_light_app().app_context():
        load_pgp_public_keys()
        add_sl_domains()
        add_invalid_mailbox_domains()
