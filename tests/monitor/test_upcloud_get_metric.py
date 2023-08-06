from monitor.upcloud import get_metric, get_metrics
from monitor.metric import UpcloudMetrics, UpcloudMetric, UpcloudRecord

import json

MOCK_RESPONSE = """
{
  "cpu_usage": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 2.744682398273781, 3.054323473090861],
        ["2022-01-21T13:11:00Z", 3.0735645433218366, 2.972423595745795],
        ["2022-01-21T13:11:30Z", 2.61619694060839, 3.1358378052207883],
        ["2022-01-21T13:12:00Z", 3.275132296130991, 4.196249043309251]
      ]
    },
    "hints": { "title": "CPU usage %" }
  },
  "disk_usage": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 5.654416415900109, 5.58959125727556],
        ["2022-01-21T13:11:00Z", 5.654416415900109, 5.58959125727556],
        ["2022-01-21T13:11:30Z", 5.654416415900109, 5.58959125727556]
      ]
    },
    "hints": { "title": "Disk space usage %" }
  },
  "diskio_reads": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 0, 0],
        ["2022-01-21T13:11:00Z", 0, 0],
        ["2022-01-21T13:11:30Z", 0, 0]
      ]
    },
    "hints": { "title": "Disk iops (reads)" }
  },
  "diskio_writes": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 3, 2],
        ["2022-01-21T13:11:00Z", 2, 3],
        ["2022-01-21T13:11:30Z", 4, 3]
      ]
    },
    "hints": { "title": "Disk iops (writes)" }
  },
  "load_average": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 0.11, 0.11],
        ["2022-01-21T13:11:00Z", 0.14, 0.1],
        ["2022-01-21T13:11:30Z", 0.14, 0.09]
      ]
    },
    "hints": { "title": "Load average (5 min)" }
  },
  "mem_usage": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 11.491766148261078, 12.318932883261219],
        ["2022-01-21T13:11:00Z", 11.511967645759277, 12.304403727425075],
        ["2022-01-21T13:11:30Z", 11.488581675749048, 12.272260458006759]
      ]
    },
    "hints": { "title": "Memory usage %" }
  },
  "net_receive": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 442, 470],
        ["2022-01-21T13:11:00Z", 439, 384],
        ["2022-01-21T13:11:30Z", 466, 458]
      ]
    },
    "hints": { "title": "Network receive (bytes/s)" }
  },
  "net_send": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 672, 581],
        ["2022-01-21T13:11:00Z", 660, 555],
        ["2022-01-21T13:11:30Z", 694, 573]
      ]
    },
    "hints": { "title": "Network transmit (bytes/s)" }
  }
}
"""


def test_get_metrics():
    response = json.loads(MOCK_RESPONSE)
    metrics = get_metrics(response)
    assert metrics == UpcloudMetrics(
        metrics=[
            UpcloudMetric(
                metric_name="cpu_usage",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:12:00Z",
                        value=3.275132296130991,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:12:00Z",
                        value=4.196249043309251,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="disk_usage",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=5.654416415900109,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=5.58959125727556,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="diskio_reads",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=0,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=0,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="diskio_writes",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=4,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=3,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="load_average",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=0.14,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=0.09,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="mem_usage",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=11.488581675749048,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=12.272260458006759,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="net_receive",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=466,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=458,
                    ),
                ],
            ),
            UpcloudMetric(
                metric_name="net_send",
                records=[
                    UpcloudRecord(
                        db_role="master",
                        label="test-1 " "(master)",
                        time="2022-01-21T13:11:30Z",
                        value=694,
                    ),
                    UpcloudRecord(
                        db_role="standby",
                        label="test-2 " "(standby)",
                        time="2022-01-21T13:11:30Z",
                        value=573,
                    ),
                ],
            ),
        ]
    )


def test_get_metric():
    response = json.loads(MOCK_RESPONSE)
    metric_name = "cpu_usage"
    metric = get_metric(response, metric_name)

    assert metric.metric_name == metric_name
    assert len(metric.records) == 2
    assert metric.records[0].label == "test-1 (master)"
    assert metric.records[0].time == "2022-01-21T13:12:00Z"
    assert metric.records[0].value == 3.275132296130991

    assert metric.records[1].label == "test-2 (standby)"
    assert metric.records[1].time == "2022-01-21T13:12:00Z"
    assert metric.records[1].value == 4.196249043309251


def test_get_metric_with_none_value():
    response_str = """
{
  "cpu_usage": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 2.744682398273781, 3.054323473090861],
        ["2022-01-21T13:11:00Z", 3.0735645433218366, 2.972423595745795],
        ["2022-01-21T13:11:30Z", null, 3.1358378052207883],
        ["2022-01-21T13:12:00Z", 3.275132296130991, null]
      ]
    },
    "hints": { "title": "CPU usage %" }
  }
}
"""
    response = json.loads(response_str)
    metric = get_metric(response, "cpu_usage")

    assert metric.records[0].label == "test-1 (master)"
    assert metric.records[0].value == 3.275132296130991
    assert metric.records[1].label == "test-2 (standby)"
    assert metric.records[1].value == 3.1358378052207883


def test_get_metric_with_none_value_in_last_two_positions():
    response_str = """
{
  "cpu_usage": {
    "data": {
      "cols": [
        { "label": "time", "type": "date" },
        { "label": "test-1 (master)", "type": "number" },
        { "label": "test-2 (standby)", "type": "number" }
      ],
      "rows": [
        ["2022-01-21T13:10:30Z", 2.744682398273781, 3.054323473090861],
        ["2022-01-21T13:11:00Z", 3.0735645433218366, 2.972423595745795],
        ["2022-01-21T13:11:30Z", null, null],
        ["2022-01-21T13:12:00Z", 3.275132296130991, null]
      ]
    },
    "hints": { "title": "CPU usage %" }
  }
}
"""
    response = json.loads(response_str)
    metric = get_metric(response, "cpu_usage")

    assert len(metric.records) == 1
    assert metric.records[0].label == "test-1 (master)"
    assert metric.records[0].value == 3.275132296130991
