import configparser
import os
import subprocess
from time import sleep
from typing import List, Dict

import arrow
import newrelic.agent

from app.db import Session
from app.log import LOG
from monitor.metric_exporter import MetricExporter

# the number of consecutive fails
# if more than _max_nb_fails, alert
# reset whenever the system comes back to normal
# a system is considered fail if incoming_queue + active_queue > 50
_nb_failed = 0

_max_nb_fails = 10

# the maximum number of emails in incoming & active queue
_max_incoming = 50

_NR_CONFIG_FILE_LOCATION_VAR = "NEW_RELIC_CONFIG_FILE"


def get_newrelic_license() -> str:
    nr_file = os.environ.get(_NR_CONFIG_FILE_LOCATION_VAR, None)
    if nr_file is None:
        raise Exception(f"{_NR_CONFIG_FILE_LOCATION_VAR} not defined")

    config = configparser.ConfigParser()
    config.read(nr_file)
    return config["newrelic"]["license_key"]


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

    proc_counts = get_num_procs(["smtp", "smtpd", "bounce", "cleanup"])
    for proc_name in proc_counts:
        LOG.d(f"Process count {proc_counts}")
        newrelic.agent.record_custom_metric(
            f"Custom/process_{proc_name}_count", proc_counts[proc_name]
        )


def nb_files(directory) -> int:
    """return the number of files in directory and its subdirectories"""
    return sum(len(files) for _, _, files in os.walk(directory))


def get_num_procs(proc_names: List[str]) -> Dict[str, int]:
    data = (
        subprocess.Popen(["ps", "ax"], stdout=subprocess.PIPE)
        .communicate()[0]
        .decode("utf-8")
    )
    return _process_ps_output(proc_names, data)


def _process_ps_output(proc_names: List[str], data: str) -> Dict[str, int]:
    proc_counts = {proc_name: 0 for proc_name in proc_names}
    lines = data.split("\n")
    for line in lines:
        entry = [field for field in line.strip().split() if field.strip()]
        if len(entry) < 5:
            continue
        if entry[4][0] == "[":
            continue
        for proc_name in proc_names:
            if entry[4] == proc_name:
                proc_counts[proc_name] += 1
    return proc_counts


@newrelic.agent.background_task()
def log_nb_db_connection():
    # get the number of connections to the DB
    r = Session.execute("select count(*) from pg_stat_activity;")
    nb_connection = list(r)[0][0]

    LOG.d("number of db connections %s", nb_connection)
    newrelic.agent.record_custom_metric("Custom/nb_db_connections", nb_connection)


@newrelic.agent.background_task()
def log_pending_to_process_events():
    r = Session.execute("select count(*) from sync_event WHERE taken_time IS NULL;")
    events_pending = list(r)[0][0]

    LOG.d("number of events pending to process %s", events_pending)
    newrelic.agent.record_custom_metric(
        "Custom/sync_events_pending_to_process", events_pending
    )


@newrelic.agent.background_task()
def log_events_pending_dead_letter():
    since = arrow.now().shift(minutes=-10).datetime
    r = Session.execute(
        """
        SELECT COUNT(*)
        FROM sync_event
        WHERE (taken_time IS NOT NULL AND taken_time < :since)
           OR (taken_time IS NULL AND created_at < :since)
        """,
        {"since": since},
    )
    events_pending = list(r)[0][0]

    LOG.d("number of events pending dead letter %s", events_pending)
    newrelic.agent.record_custom_metric(
        "Custom/sync_events_pending_dead_letter", events_pending
    )


if __name__ == "__main__":
    exporter = MetricExporter(get_newrelic_license())
    while True:
        log_postfix_metrics()
        log_nb_db_connection()
        log_pending_to_process_events()
        log_events_pending_dead_letter()
        Session.close()

        exporter.run()

        # 1 min
        sleep(60)
