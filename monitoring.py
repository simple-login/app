import os
from time import sleep

from app.config import HOST
from app.extensions import db
from app.log import LOG
from app.models import Monitoring
from server import create_app

# the number of consecutive fails
# if more than 3 fails, alert
# reset whenever the system comes back to normal
# a system is considered fail if incoming_queue + active_queue > 20
_nb_failed = 0


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

    global _nb_failed
    # alert when too many emails in incoming + active queue
    # 20 is an arbitrary number here
    if incoming_queue + active_queue > 20:
        _nb_failed += 1

        if _nb_failed > 3:
            # reset
            _nb_failed = 0

            LOG.exception(
                "Too many emails in incoming & active queue %s %s",
                incoming_queue,
                active_queue,
            )
    else:
        _nb_failed = 0


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
