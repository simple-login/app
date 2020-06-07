"""Initial loading script"""
from app.models import Mailbox, Contact
from app.log import LOG
from app.extensions import db
from app.pgp_utils import load_public_key
from server import create_app


def load_pgp_public_keys():
    """Load PGP public key to keyring"""
    for mailbox in Mailbox.query.filter(Mailbox.pgp_public_key != None).all():
        LOG.d("Load PGP key for mailbox %s", mailbox)
        fingerprint = load_public_key(mailbox.pgp_public_key)

        # sanity check
        if fingerprint != mailbox.pgp_finger_print:
            LOG.error("fingerprint %s different for mailbox %s", fingerprint, mailbox)
            mailbox.pgp_finger_print = fingerprint
    db.session.commit()

    for contact in Contact.query.filter(Contact.pgp_public_key != None).all():
        LOG.d("Load PGP key for %s", contact)
        fingerprint = load_public_key(contact.pgp_public_key)

        # sanity check
        if fingerprint != contact.pgp_finger_print:
            LOG.error("fingerprint %s different for contact %s", fingerprint, contact)
            contact.pgp_finger_print = fingerprint

    db.session.commit()

    LOG.d("Finish load_pgp_public_keys")


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        load_pgp_public_keys()
