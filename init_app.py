"""Initial loading script"""
from app.models import Mailbox
from app.log import LOG
from app.extensions import db
from app.pgp_utils import load_public_key
from server import create_app


def load_pgp_public_keys(app):
    """Load PGP public key to keyring"""
    with app.app_context():
        for mailbox in Mailbox.query.filter(Mailbox.pgp_public_key != None).all():
            LOG.d("Load PGP key for mailbox %s", mailbox)
            fingerprint = load_public_key(mailbox.pgp_public_key)

            # sanity check
            if fingerprint != mailbox.pgp_finger_print:
                LOG.error(
                    "fingerprint %s different for mailbox %s", fingerprint, mailbox
                )
                mailbox.pgp_finger_print = fingerprint

        db.session.commit()


if __name__ == "__main__":
    app = create_app()

    with app.app_context():
        load_pgp_public_keys(app)
