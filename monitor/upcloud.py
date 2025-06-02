from app.log import LOG
from monitor.metric import UpcloudMetric, UpcloudMetrics, UpcloudRecord

import base64
import requests
from typing import Any


BASE_URL = "https://api.upcloud.com"


def get_metric(json: Any, metric: str) -> UpcloudMetric:
    records = []

    if metric in json:
        metric_data = json[metric]
        data = metric_data["data"]
        cols = list(map(lambda x: x["label"], data["cols"][1:]))
        latest = data["rows"][-1]
        time = latest[0]
        for column_idx in range(len(cols)):
            value = latest[1 + column_idx]

            # If the latest value is None, try to fetch the second to last
            if value is None:
                value = data["rows"][-2][1 + column_idx]

            if value is not None:
                label = cols[column_idx]
                if "(master)" in label:
                    db_role = "master"
                else:
                    db_role = "standby"
                records.append(
                    UpcloudRecord(time=time, db_role=db_role, label=label, value=value)
                )
            else:
                LOG.warning(f"Could not get value for metric {metric}")

    return UpcloudMetric(metric_name=metric, records=records)


def get_metrics(json: Any) -> UpcloudMetrics:
    return UpcloudMetrics(
        metrics=[
            get_metric(json, "cpu_usage"),
            get_metric(json, "disk_usage"),
            get_metric(json, "diskio_reads"),
            get_metric(json, "diskio_writes"),
            get_metric(json, "load_average"),
            get_metric(json, "mem_usage"),
            get_metric(json, "net_receive"),
            get_metric(json, "net_send"),
        ]
    )


class UpcloudClient:
    def __init__(self, username: str, password: str):
        if not username:
            raise Exception("UpcloudClient username must be set")
        if not password:
            raise Exception("UpcloudClient password must be set")

        client = requests.Session()
        encoded_auth = base64.b64encode(
            f"{username}:{password}".encode("utf-8")
        ).decode("utf-8")
        client.headers = {"Authorization": f"Basic {encoded_auth}"}
        self.__client = client

    def get_metrics(self, db_uuid: str) -> UpcloudMetrics:
        url = f"{BASE_URL}/1.3/database/{db_uuid}/metrics?period=hour"
        LOG.d(f"Performing request to {url}")
        response = self.__client.get(url)
        LOG.d(f"Status code: {response.status_code}")
        if response.status_code != 200:
            return UpcloudMetrics(metrics=[])

        as_json = response.json()

        return get_metrics(as_json)
