import os
from time import sleep

from app.config import HOST
from app.extensions import db
from app.log import LOG
from app.models import Monitoring
from server import create_app


def get_stats():
    """Look at different metrics and alert appropriately"""
    incoming_queue = nb_files("/var/spool/postfix/incoming")
    active_queue = nb_files("/var/spool/postfix/active")
    deferred_queue = nb_files("/var/spool/postfix/deferred")
    LOG.d("postfix queue sizes %s %s %s", incoming_queue, active_queue, deferred_queue)

    Monitoring.create(
        host=HOST,
        incoming_queue=incoming_queue,
        active_queue=active_queue,
        deferred_queue=deferred_queue,
    )
    db.session.commit()

    # alert when too many emails in incoming + active queue
    # 20 is an arbitrary number here
    if incoming_queue + active_queue > 20:
        LOG.exception(
            "Too many emails in incoming & active queue %s %s",
            incoming_queue,
            active_queue,
        )


def nb_files(directory) -> int:
    """return the number of files in directory and its sub-directories"""
    return sum(len(files) for _, _, files in os.walk(directory))


if __name__ == "__main__":
    while True:
        app = create_app()
        with app.app_context():
            get_stats()

        # 5 min
        sleep(300)
