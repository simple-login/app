#!/usr/bin/env python3
"""Generate the SimpleLogin alerts dashboard and the matching Grafana alert rules.

Every alert is defined once below. The script writes:

* ``simplelogin-alerts.json``: a Grafana dashboard with one panel per alert.
  Each panel graphs the exact expression the alert rule evaluates and draws
  the alert threshold on it.
* ``simplelogin-alert-rules.yaml``: Grafana-managed alert rules in the file
  provisioning format. Each rule points back to its panel through the
  ``__dashboardUid__`` / ``__panelId__`` annotations, so firing alerts show up
  as annotations on the right graph.

Run it after editing a threshold so both files stay in sync::

    python3 monitor/grafana/generate_alerts.py
"""

import json
from pathlib import Path

OUT_DIR = Path(__file__).parent
DASHBOARD_UID = "simplelogin-alerts"
DATASOURCE_UID = "ef2extxyzeigwc"  # promext
FOLDER = "SimpleLogin"
RULE_ENV = "prod-proton"

# Selector placeholders. ``@S`` is the selector for SimpleLogin metrics and
# ``@U`` the one for ``up`` (which has no ``env`` label and also covers
# staging). Dashboard panels use the template variables, alert rules use the
# fixed production values.
PANEL_SEL = {
    "@S": 'job="simplelogin-upcloud", env="$env", instance=~"$instance"',
    "@U": 'job="simplelogin-upcloud", instance=~"$instance"',
}
RULE_SEL = {
    "@S": f'job="simplelogin-upcloud", env="{RULE_ENV}"',
    "@U": 'job="simplelogin-upcloud", instance=~"prod.*"',
}

HTTP = "simplelogin_custom_event_httpresponsestatus_total"
INCOMING = "simplelogin_custom_number_incoming_email_count"
HANDLERS = 'process_start_time_seconds{@S, container=~"sl-email.*"}'
CONTAINER_GROUP = '"group", "$1", "container", "(sl-[a-z-]+?)(-[0-9]+)?"'


def rule(uid, title, op, threshold, severity, for_, summary, no_data="OK"):
    return {
        "uid": uid,
        "title": title,
        "op": op,  # "gt" or "lt"
        "threshold": threshold,
        "severity": severity,  # "warning" or "critical"
        "for": for_,
        "summary": summary,
        "no_data": no_data,
    }


# Each section becomes a dashboard row and an alert rule group. Each panel
# holds one expression and one or more rules on it (for example a warning and
# a critical disk threshold).
SECTIONS = [
    {
        "title": "Availability",
        "group": "simplelogin-availability",
        "panels": [
            {
                "title": "Scrape target up (per host)",
                "expr": "min by (instance) (up{@U})",
                "legend": "{{instance}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-target-down",
                        "SimpleLogin host not scraped",
                        "lt",
                        1,
                        "critical",
                        "3m",
                        "Prometheus cannot scrape {{ $labels.instance }}: the host or its exporter is down.",
                        no_data="Alerting",
                    )
                ],
            },
            {
                "title": "Email handler processes vs 1h max (per host)",
                "expr": (
                    f"(count by (instance) ({HANDLERS}) or count by (instance) ({HANDLERS} offset 15m) * 0)"
                    f" / max_over_time((count by (instance) ({HANDLERS}))[1h:1m])"
                ),
                "legend": "{{instance}}",
                "unit": "percentunit",
                "rules": [
                    rule(
                        "sl-email-handlers-lost",
                        "SimpleLogin email handler processes lost",
                        "lt",
                        0.8,
                        "critical",
                        "5m",
                        "{{ $labels.instance }} runs less than 80% of the email handler processes it had in the last hour.",
                    )
                ],
            },
            {
                "title": "Container restarts in 15m (max per container group)",
                "expr": (
                    "max by (instance, group) (label_replace("
                    "changes(process_start_time_seconds{@S}[15m]), "
                    + CONTAINER_GROUP
                    + "))"
                ),
                "legend": "{{instance}} {{group}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-crash-loop",
                        "SimpleLogin container crash looping",
                        "gt",
                        3,
                        "warning",
                        "5m",
                        "A {{ $labels.group }} container on {{ $labels.instance }} restarted more than 3 times in 15 minutes.",
                    )
                ],
            },
        ],
    },
    {
        "title": "HTTP",
        "group": "simplelogin-http",
        "panels": [
            {
                "title": "Web app (sl-app) 5xx ratio",
                "expr": (
                    f'sum(rate({HTTP}{{@S, container=~"sl-app.*", code=~"5.."}}[5m]))'
                    f' / sum(rate({HTTP}{{@S, container=~"sl-app.*"}}[5m]))'
                    f' and on() sum(increase({HTTP}{{@S, container=~"sl-app.*", code=~"5.."}}[5m])) > 5'
                ),
                "legend": "5xx ratio",
                "unit": "percentunit",
                "rules": [
                    rule(
                        "sl-app-5xx",
                        "SimpleLogin web app 5xx errors",
                        "gt",
                        0.05,
                        "critical",
                        "5m",
                        "More than 5% of sl-app responses are 5xx (only counted when there are more than 5 errors in 5 minutes).",
                    )
                ],
            },
            {
                "title": "Partner API (sl-partner-api) 5xx ratio",
                "expr": (
                    f'sum(rate({HTTP}{{@S, container=~"sl-partner-api.*", code=~"5.."}}[5m]))'
                    f' / sum(rate({HTTP}{{@S, container=~"sl-partner-api.*"}}[5m]))'
                    f' and on() sum(increase({HTTP}{{@S, container=~"sl-partner-api.*", code=~"5.."}}[5m])) > 5'
                ),
                "legend": "5xx ratio",
                "unit": "percentunit",
                "rules": [
                    rule(
                        "sl-partner-api-5xx",
                        "SimpleLogin partner API 5xx errors",
                        "gt",
                        0.02,
                        "critical",
                        "5m",
                        "More than 2% of sl-partner-api responses are 5xx (only counted when there are more than 5 errors in 5 minutes).",
                    )
                ],
            },
            {
                "title": "Web app (sl-app) requests /s",
                "expr": f'sum(rate({HTTP}{{@S, container=~"sl-app.*"}}[5m]))',
                "legend": "requests /s",
                "unit": "reqps",
                "rules": [
                    rule(
                        "sl-app-no-traffic",
                        "SimpleLogin web app receives no traffic",
                        "lt",
                        0.05,
                        "critical",
                        "10m",
                        "sl-app served almost no requests for 10 minutes: it is down or unreachable.",
                        no_data="Alerting",
                    )
                ],
            },
            {
                "title": "Partner API (sl-partner-api) requests /s",
                "expr": f'sum(rate({HTTP}{{@S, container=~"sl-partner-api.*"}}[5m]))',
                "legend": "requests /s",
                "unit": "reqps",
                "rules": [
                    rule(
                        "sl-partner-api-no-traffic",
                        "SimpleLogin partner API receives no traffic",
                        "lt",
                        0.1,
                        "critical",
                        "10m",
                        "sl-partner-api served almost no requests for 10 minutes: it is down or unreachable.",
                        no_data="Alerting",
                    )
                ],
            },
        ],
    },
    {
        "title": "Receiving email",
        "group": "simplelogin-email-receiving",
        "panels": [
            {
                "title": "Incoming emails /s (total)",
                "expr": f'sum(rate({INCOMING}{{@S, container=~"sl-email.*"}}[5m]))',
                "legend": "emails /s",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-incoming-email-low",
                        "SimpleLogin incoming email volume collapsed",
                        "lt",
                        5,
                        "critical",
                        "10m",
                        "Fewer than 5 emails/s are handled across all hosts: inbound mail is not reaching the email handlers.",
                        no_data="Alerting",
                    )
                ],
            },
            {
                "title": "Incoming emails /s per host",
                "expr": f'sum by (instance) (rate({INCOMING}{{@S, container=~"sl-email.*"}}[10m]))',
                "legend": "{{instance}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-host-not-receiving",
                        "SimpleLogin host not receiving email",
                        "lt",
                        0.1,
                        "critical",
                        "10m",
                        "{{ $labels.instance }} handled almost no incoming email for 10 minutes while the other hosts keep receiving.",
                    )
                ],
            },
            {
                "title": "Average email handler time",
                "expr": (
                    'sum(rate(simplelogin_custom_email_handler_time_sum{@S, container=~"sl-email.*"}[5m]))'
                    ' / sum(rate(simplelogin_custom_email_handler_time_count{@S, container=~"sl-email.*"}[5m]))'
                ),
                "legend": "avg",
                "unit": "s",
                "rules": [
                    rule(
                        "sl-email-handler-slow",
                        "SimpleLogin email handling is slow",
                        "gt",
                        5,
                        "warning",
                        "10m",
                        "Handling an incoming email takes more than 5s on average (normally under 1s).",
                    )
                ],
            },
        ],
    },
    {
        "title": "Sending email",
        "group": "simplelogin-email-sending",
        "panels": [
            {
                "title": "SMTP error ratio per host (errors / send attempts)",
                "expr": (
                    "sum by (instance) (rate(simplelogin_custom_event_smtperror_total{@S}[5m]))"
                    " / sum by (instance) (rate(simplelogin_custom_smtp_sending_time_count{@S}[5m]))"
                ),
                "legend": "{{instance}}",
                "unit": "percentunit",
                "rules": [
                    rule(
                        "sl-smtp-errors",
                        "SimpleLogin SMTP send errors",
                        "gt",
                        0.1,
                        "critical",
                        "10m",
                        "More than 10% of SMTP sends from {{ $labels.instance }} fail (disconnects, timeouts, refused connections).",
                    )
                ],
            },
            {
                "title": "Average SMTP servers tried per send",
                "expr": (
                    "sum by (instance) (rate(simplelogin_custom_smtp_servers_tried_sum{@S}[5m]))"
                    " / sum by (instance) (rate(simplelogin_custom_smtp_servers_tried_count{@S}[5m]))"
                ),
                "legend": "{{instance}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-smtp-failover",
                        "SimpleLogin SMTP failing over to backup servers",
                        "gt",
                        1.3,
                        "warning",
                        "10m",
                        "{{ $labels.instance }} needs more than 1.3 SMTP servers per send on average: the primary relay is failing.",
                    )
                ],
            },
            {
                "title": "Average SMTP connection time per host",
                "expr": (
                    "sum by (instance) (rate(simplelogin_custom_smtp_connection_time_sum{@S}[5m]))"
                    " / sum by (instance) (rate(simplelogin_custom_smtp_connection_time_count{@S}[5m]))"
                ),
                "legend": "{{instance}}",
                "unit": "s",
                "rules": [
                    rule(
                        "sl-smtp-connect-slow",
                        "SimpleLogin SMTP connections are slow",
                        "gt",
                        1,
                        "warning",
                        "10m",
                        "Opening an SMTP connection from {{ $labels.instance }} takes more than 1s on average (normally about 0.1s).",
                    )
                ],
            },
            {
                "title": "PGP encryption failure ratio",
                "expr": (
                    'sum(rate(simplelogin_custom_event_pgpencrypt_total{@S, success="fail"}[5m]))'
                    " / sum(rate(simplelogin_custom_event_pgpencrypt_total{@S}[5m]))"
                ),
                "legend": "failure ratio",
                "unit": "percentunit",
                "rules": [
                    rule(
                        "sl-pgp-failures",
                        "SimpleLogin PGP encryption failures",
                        "gt",
                        0.1,
                        "warning",
                        "15m",
                        "More than 10% of PGP encryptions fail (normally about 1%).",
                    )
                ],
            },
        ],
    },
    {
        "title": "Partner event sync & jobs",
        "group": "simplelogin-sync-jobs",
        "panels": [
            {
                "title": "Partner events processed / stored",
                "expr": (
                    "(sum(rate(simplelogin_custom_sync_event_processed_count{@S}[15m])) or vector(0))"
                    " / sum(rate(simplelogin_custom_event_eventstoredtodb_total{@S}[15m]))"
                ),
                "legend": "processed / stored",
                "unit": "percentunit",
                "rules": [
                    rule(
                        "sl-sync-not-processing",
                        "SimpleLogin partner events not processed",
                        "lt",
                        0.5,
                        "critical",
                        "15m",
                        "Less than half of the partner events stored in the DB are being sent: the event listener is stuck.",
                    )
                ],
            },
            {
                "title": "Partner event end-to-end lag (avg)",
                "expr": (
                    "sum(rate(simplelogin_custom_sync_event_elapsed_time_sum{@S}[5m]))"
                    " / sum(rate(simplelogin_custom_sync_event_elapsed_time_count{@S}[5m]))"
                ),
                "legend": "avg lag",
                "unit": "s",
                "rules": [
                    rule(
                        "sl-sync-lag",
                        "SimpleLogin partner event sync lagging",
                        "gt",
                        120,
                        "warning",
                        "10m",
                        "Partner events take more than 2 minutes on average to be delivered (normally a few seconds).",
                    )
                ],
            },
            {
                "title": "Sync events failed /min",
                "expr": "60 * sum(rate(simplelogin_custom_sync_event_failed_count{@S}[5m]))",
                "legend": "failed /min",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-sync-failed",
                        "SimpleLogin partner sync events failing",
                        "gt",
                        1,
                        "warning",
                        "10m",
                        "More than 1 partner sync event per minute fails.",
                    )
                ],
            },
            {
                "title": "Partner webhook non-2xx /min",
                "expr": '60 * sum(rate(simplelogin_custom_event_eventsenttopartner_total{@S, http_code!~"2.."}[5m]))',
                "legend": "non-2xx /min",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-partner-webhook-errors",
                        "SimpleLogin partner webhook errors",
                        "gt",
                        1,
                        "warning",
                        "10m",
                        "The partner rejects more than 1 event per minute (non-2xx responses).",
                    )
                ],
            },
            {
                "title": "Jobs in error /min",
                "expr": '60 * sum(rate(simplelogin_custom_event_jobprocessed_total{@S, result="error"}[5m]))',
                "legend": "errors /min",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-job-errors",
                        "SimpleLogin jobs failing",
                        "gt",
                        10,
                        "warning",
                        "15m",
                        "More than 10 jobs per minute end in error (normally under 2).",
                    )
                ],
            },
            {
                "title": "Jobs picked /min",
                "expr": "60 * sum(rate(simplelogin_custom_event_processjob_total{@S}[10m]))",
                "legend": "jobs /min",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-job-runner-stalled",
                        "SimpleLogin job runner stalled",
                        "lt",
                        1,
                        "warning",
                        "30m",
                        "The job runner picked fewer than 1 job per minute for 30 minutes (normally about 60).",
                        no_data="Alerting",
                    )
                ],
            },
        ],
    },
    {
        "title": "Database (pgdog)",
        "group": "simplelogin-database",
        "panels": [
            {
                "title": "Clients waiting for a DB connection",
                "expr": 'max by (instance) (simplelogin_pgdog_cl_waiting{@S, container=~"sl-pgdog"})',
                "legend": "{{instance}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-db-clients-waiting",
                        "SimpleLogin clients waiting for DB connections",
                        "gt",
                        5,
                        "warning",
                        "2m",
                        "More than 5 clients on {{ $labels.instance }} are queued for a database connection: the pool is exhausted.",
                    )
                ],
            },
            {
                "title": "DB server errors + checkout timeouts /min",
                "expr": (
                    '60 * (sum by (instance) (rate(simplelogin_pgdog_total_server_errors{@S, container=~"sl-pgdog"}[5m]))'
                    ' + sum by (instance) (rate(simplelogin_pgdog_total_checkout_timeouts{@S, container=~"sl-pgdog"}[5m])))'
                ),
                "legend": "{{instance}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-db-errors",
                        "SimpleLogin DB pool errors",
                        "gt",
                        1,
                        "warning",
                        "5m",
                        "pgdog on {{ $labels.instance }} reports server errors or checkout timeouts.",
                    )
                ],
            },
            {
                "title": "Banned DB servers",
                "expr": 'max by (instance) (simplelogin_pgdog_banned{@S, container=~"sl-pgdog"})',
                "legend": "{{instance}}",
                "unit": "none",
                "rules": [
                    rule(
                        "sl-db-banned",
                        "SimpleLogin DB server banned by pgdog",
                        "gt",
                        0,
                        "critical",
                        "2m",
                        "pgdog on {{ $labels.instance }} banned a database server after repeated failures.",
                    )
                ],
            },
        ],
    },
    {
        "title": "Hosts",
        "group": "simplelogin-hosts",
        "panels": [
            {
                "title": "Disk used %",
                "expr": "max by (instance, path) (simplelogin_host_disk_used_percent{@S})",
                "legend": "{{instance}} {{path}}",
                "unit": "percent",
                "rules": [
                    rule(
                        "sl-disk-warning",
                        "SimpleLogin disk space low",
                        "gt",
                        85,
                        "warning",
                        "10m",
                        "{{ $labels.path }} on {{ $labels.instance }} is more than 85% full.",
                    ),
                    rule(
                        "sl-disk-critical",
                        "SimpleLogin disk almost full",
                        "gt",
                        95,
                        "critical",
                        "5m",
                        "{{ $labels.path }} on {{ $labels.instance }} is more than 95% full.",
                    ),
                ],
            },
            {
                "title": "Disk free predicted in 24h (from last 6h trend)",
                "expr": "max by (instance, path) (predict_linear(simplelogin_host_disk_free{@S}[6h], 86400))",
                "legend": "{{instance}} {{path}}",
                "unit": "bytes",
                "rules": [
                    rule(
                        "sl-disk-fill-24h",
                        "SimpleLogin disk will fill within 24h",
                        "lt",
                        0,
                        "warning",
                        "30m",
                        "At the current rate {{ $labels.path }} on {{ $labels.instance }} runs out of space within 24 hours.",
                    )
                ],
            },
            {
                "title": "Memory used %",
                "expr": "max by (instance) (simplelogin_host_mem_used_percent{@S})",
                "legend": "{{instance}}",
                "unit": "percent",
                "rules": [
                    rule(
                        "sl-memory-high",
                        "SimpleLogin host memory high",
                        "gt",
                        90,
                        "warning",
                        "10m",
                        "{{ $labels.instance }} uses more than 90% of its memory (normally under 50%).",
                    )
                ],
            },
            {
                "title": "CPU used %",
                "expr": 'max by (instance) (simplelogin_host_cpu_usage_active{@S, cpu="cpu-total"})',
                "legend": "{{instance}}",
                "unit": "percent",
                "rules": [
                    rule(
                        "sl-cpu-high",
                        "SimpleLogin host CPU saturated",
                        "gt",
                        95,
                        "warning",
                        "15m",
                        "{{ $labels.instance }} CPU is above 95% for 15 minutes.",
                    )
                ],
            },
            {
                "title": "CPU iowait %",
                "expr": 'max by (instance) (simplelogin_host_cpu_usage_iowait{@S, cpu="cpu-total"})',
                "legend": "{{instance}}",
                "unit": "percent",
                "rules": [
                    rule(
                        "sl-iowait-high",
                        "SimpleLogin host disk I/O saturated",
                        "gt",
                        20,
                        "warning",
                        "10m",
                        "{{ $labels.instance }} spends more than 20% of CPU time waiting on disk I/O.",
                    )
                ],
            },
        ],
    },
]

SEVERITY_COLOR = {"warning": "orange", "critical": "red"}


def substitute(expr, selectors):
    for key, value in selectors.items():
        expr = expr.replace(key, value)
    return expr


def describe(r):
    sign = ">" if r["op"] == "gt" else "<"
    return f'{r["severity"].upper()}: {r["title"]} when {sign} {r["threshold"]} for {r["for"]}'


def thresholds(rules):
    lt = [r for r in rules if r["op"] == "lt"]
    if lt:
        r = lt[0]
        return [
            {"color": SEVERITY_COLOR[r["severity"]], "value": None},
            {"color": "green", "value": r["threshold"]},
        ]
    steps = [{"color": "green", "value": None}]
    for r in sorted(rules, key=lambda r: r["threshold"]):
        steps.append({"color": SEVERITY_COLOR[r["severity"]], "value": r["threshold"]})
    return steps


def build():
    panels = [
        {
            "id": 1,
            "type": "alertlist",
            "title": "SimpleLogin alerts (firing, pending, no data, error)",
            "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
            "options": {
                "viewMode": "list",
                "groupMode": "default",
                "groupBy": [],
                "maxItems": 50,
                "sortOrder": 1,
                "dashboardAlerts": False,
                "alertName": "",
                "alertInstanceLabelFilter": '{service="simplelogin"}',
                "showInstances": True,
                "stateFilter": {
                    "firing": True,
                    "pending": True,
                    "noData": True,
                    "error": True,
                    "normal": False,
                },
            },
        }
    ]
    groups = []
    panel_id = 2
    y = 8
    for section in SECTIONS:
        panels.append(
            {
                "id": panel_id,
                "type": "row",
                "title": section["title"],
                "collapsed": False,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
                "panels": [],
            }
        )
        panel_id += 1
        y += 1
        group_rules = []
        for i, panel in enumerate(section["panels"]):
            x = (i % 3) * 8
            if i and i % 3 == 0:
                y += 8
            rules = panel["rules"]
            panels.append(
                {
                    "id": panel_id,
                    "type": "timeseries",
                    "title": panel["title"],
                    "description": "\n".join(
                        describe(r) + ". " + r["summary"] for r in rules
                    ),
                    "datasource": {"type": "prometheus", "uid": "${datasource}"},
                    "gridPos": {"h": 8, "w": 8, "x": x, "y": y},
                    "targets": [
                        {
                            "refId": "A",
                            "datasource": {
                                "type": "prometheus",
                                "uid": "${datasource}",
                            },
                            "expr": substitute(panel["expr"], PANEL_SEL),
                            "legendFormat": panel["legend"],
                            "range": True,
                        }
                    ],
                    "fieldConfig": {
                        "defaults": {
                            "unit": panel["unit"],
                            "color": {"mode": "palette-classic"},
                            "custom": {
                                "drawStyle": "line",
                                "lineWidth": 1,
                                "fillOpacity": 0,
                                "showPoints": "never",
                                "spanNulls": False,
                                "thresholdsStyle": {"mode": "line+area"},
                            },
                            "thresholds": {
                                "mode": "absolute",
                                "steps": thresholds(rules),
                            },
                        },
                        "overrides": [],
                    },
                    "options": {
                        "legend": {
                            "displayMode": "list",
                            "placement": "bottom",
                            "showLegend": True,
                        },
                        "tooltip": {"mode": "multi", "sort": "desc"},
                    },
                }
            )
            for r in rules:
                group_rules.append(alert_rule(panel, r, panel_id))
            panel_id += 1
        y += 8
        groups.append(
            {
                "orgId": 1,
                "name": section["group"],
                "folder": FOLDER,
                "interval": "1m",
                "rules": group_rules,
            }
        )

    dashboard = {
        "uid": DASHBOARD_UID,
        "title": "SimpleLogin - Alerts",
        "description": (
            "One panel per alert rule. Each panel graphs the expression its alert evaluates "
            "and shades the alerting range. Generated by monitor/grafana/generate_alerts.py."
        ),
        "tags": ["simplelogin", "alerts", "prometheus"],
        "timezone": "utc",
        "editable": True,
        "graphTooltip": 1,
        "refresh": "1m",
        "schemaVersion": 39,
        "time": {"from": "now-6h", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "datasource",
                    "label": "Datasource",
                    "type": "datasource",
                    "query": "prometheus",
                    "regex": "promext.*",
                    "current": {"text": "promext", "value": DATASOURCE_UID},
                    "hide": 0,
                },
                {
                    "name": "env",
                    "label": "Env",
                    "type": "query",
                    "datasource": {"type": "prometheus", "uid": "${datasource}"},
                    "query": {
                        "query": 'label_values(simplelogin_host_mem_used_percent{job="simplelogin-upcloud"}, env)',
                        "refId": "env",
                    },
                    "definition": 'label_values(simplelogin_host_mem_used_percent{job="simplelogin-upcloud"}, env)',
                    "current": {"text": RULE_ENV, "value": RULE_ENV},
                    "refresh": 2,
                    "sort": 1,
                    "hide": 0,
                },
                {
                    "name": "instance",
                    "label": "Host",
                    "type": "query",
                    "datasource": {"type": "prometheus", "uid": "${datasource}"},
                    "query": {
                        "query": 'label_values(simplelogin_host_mem_used_percent{job="simplelogin-upcloud", env="$env"}, instance)',
                        "refId": "instance",
                    },
                    "definition": 'label_values(simplelogin_host_mem_used_percent{job="simplelogin-upcloud", env="$env"}, instance)',
                    "multi": True,
                    "includeAll": True,
                    "allValue": ".*",
                    "current": {"text": ["All"], "value": ["$__all"]},
                    "refresh": 2,
                    "sort": 1,
                    "hide": 0,
                },
            ]
        },
        "annotations": {
            "list": [
                {
                    "name": "Annotations & Alerts",
                    "builtIn": 1,
                    "enable": True,
                    "hide": True,
                    "iconColor": "rgba(0, 211, 255, 1)",
                    "type": "dashboard",
                    "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                },
                {
                    "name": "Process restarts (deploys)",
                    "enable": True,
                    "iconColor": "purple",
                    "datasource": {"type": "prometheus", "uid": "${datasource}"},
                    "expr": (
                        'sum by (instance) (changes(process_start_time_seconds{job="simplelogin-upcloud", '
                        'env="$env", instance=~"$instance", container=~"sl-app.*"}[2m])) > 0'
                    ),
                    "step": "1m",
                    "titleFormat": "sl-app restarted",
                    "textFormat": "{{instance}}",
                },
            ]
        },
        "panels": panels,
    }
    return dashboard, {"apiVersion": 1, "groups": groups}


def alert_rule(panel, r, panel_id):
    return {
        "uid": r["uid"],
        "title": r["title"],
        "condition": "C",
        "data": [
            {
                "refId": "A",
                "relativeTimeRange": {"from": 600, "to": 0},
                "datasourceUid": DATASOURCE_UID,
                "model": {
                    "refId": "A",
                    "expr": substitute(panel["expr"], RULE_SEL),
                    "instant": True,
                    "range": False,
                    "legendFormat": panel["legend"],
                },
            },
            {
                "refId": "C",
                "relativeTimeRange": {"from": 0, "to": 0},
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "A",
                    "conditions": [
                        {"evaluator": {"type": r["op"], "params": [r["threshold"]]}}
                    ],
                },
            },
        ],
        "for": r["for"],
        "noDataState": r["no_data"],
        "execErrState": "Error",
        "labels": {"service": "simplelogin", "severity": r["severity"]},
        "annotations": {
            "summary": r["summary"],
            "description": describe(r),
            "__dashboardUid__": DASHBOARD_UID,
            "__panelId__": str(panel_id),
        },
    }


def to_yaml(value, indent=0):
    """Minimal YAML writer (JSON scalars are valid YAML), avoids a PyYAML dependency."""
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{k}:")
                lines.append(to_yaml(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {json.dumps(v)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)) and item:
                body = to_yaml(item, indent + 1)
                lines.append(f"{pad}- {body.lstrip()}")
            else:
                lines.append(f"{pad}- {json.dumps(item)}")
    return "\n".join(lines)


def main():
    dashboard, rules = build()
    (OUT_DIR / "simplelogin-alerts.json").write_text(
        json.dumps(dashboard, indent=2) + "\n"
    )
    header = (
        "# Grafana-managed alert rules for SimpleLogin (file provisioning format).\n"
        "# Generated by monitor/grafana/generate_alerts.py: edit thresholds there, not here.\n"
        "# Every rule carries the labels service=simplelogin and severity=warning|critical\n"
        "# so a notification policy can route on them.\n"
    )
    (OUT_DIR / "simplelogin-alert-rules.yaml").write_text(
        header + to_yaml(rules) + "\n"
    )
    count = sum(len(g["rules"]) for g in rules["groups"])
    print(f"{count} alert rules in {len(rules['groups'])} groups")


if __name__ == "__main__":
    main()
