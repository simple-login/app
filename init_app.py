"""Initial loading script"""
from app.config import ALIAS_DOMAINS, PREMIUM_ALIAS_DOMAINS
from app.models import Mailbox, Contact, SLDomain
from app.log import LOG
from app.extensions import db
from app.pgp_utils import load_public_key
from server import create_app


def load_pgp_public_keys():
    """Load PGP public key to keyring"""
    for mailbox in Mailbox.query.filter(Mailbox.pgp_public_key.isnot(None)).all():
        LOG.d("Load PGP key for mailbox %s", mailbox)
        fingerprint = load_public_key(mailbox.pgp_public_key)

        # sanity check
        if fingerprint != mailbox.pgp_finger_print:
            LOG.exception(
                "fingerprint %s different for mailbox %s", fingerprint, mailbox
            )
            mailbox.pgp_finger_print = fingerprint
    db.session.commit()

    for contact in Contact.query.filter(Contact.pgp_public_key.isnot(None)).all():
        LOG.d("Load PGP key for %s", contact)
        fingerprint = load_public_key(contact.pgp_public_key)

        # sanity check
        if fingerprint != contact.pgp_finger_print:
            LOG.exception(
                "fingerprint %s different for contact %s", fingerprint, contact
            )
            contact.pgp_finger_print = fingerprint

    db.session.commit()

    LOG.d("Finish load_pgp_public_keys")


def add_sl_domains():
    for alias_domain in ALIAS_DOMAINS:
        if SLDomain.get_by(domain=alias_domain):
            LOG.d("%s is already a SL domain", alias_domain)
        else:
            LOG.info("Add %s to SL domain", alias_domain)
            SLDomain.create(domain=alias_domain)

    for premium_domain in PREMIUM_ALIAS_DOMAINS:
        if SLDomain.get_by(domain=premium_domain):
            LOG.d("%s is already a SL domain", premium_domain)
        else:
            LOG.info("Add %s to SL domain", premium_domain)
            SLDomain.create(domain=premium_domain, premium_only=True)

    db.session.commit()


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        load_pgp_public_keys()
        add_sl_domains()
