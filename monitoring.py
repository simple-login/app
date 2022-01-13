import os
from time import sleep

import newrelic.agent

from app.db import Session
from app.log import LOG

# the number of consecutive fails
# if more than _max_nb_fails, alert
# reset whenever the system comes back to normal
# a system is considered fail if incoming_queue + active_queue > 50
_nb_failed = 0

_max_nb_fails = 10

# the maximum number of emails in incoming & active queue
_max_incoming = 50


@newrelic.agent.background_task()
def log_postfix_metrics():
    """Look at different metrics and alert appropriately"""
    incoming_queue = nb_files("/var/spool/postfix/incoming")
    active_queue = nb_files("/var/spool/postfix/active")
    deferred_queue = nb_files("/var/spool/postfix/deferred")
    LOG.d("postfix queue sizes %s %s %s", incoming_queue, active_queue, deferred_queue)

    newrelic.agent.record_custom_metric("Custom/postfix_incoming_queue", incoming_queue)
    newrelic.agent.record_custom_metric("Custom/postfix_active_queue", active_queue)
    newrelic.agent.record_custom_metric("Custom/postfix_deferred_queue", deferred_queue)


def nb_files(directory) -> int:
    """return the number of files in directory and its subdirectories"""
    return sum(len(files) for _, _, files in os.walk(directory))


@newrelic.agent.background_task()
def log_nb_db_connection():
    # get the number of connections to the DB
    r = Session.execute("select count(*) from pg_stat_activity;")
    nb_connection = list(r)[0][0]

    LOG.d("number of db connections %s", nb_connection)
    newrelic.agent.record_custom_metric("Custom/nb_db_connections", nb_connection)


if __name__ == "__main__":
    while True:
        log_postfix_metrics()
        log_nb_db_connection()

        # 1 min
        sleep(60)
