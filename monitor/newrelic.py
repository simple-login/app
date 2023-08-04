from monitor.metric import UpcloudMetrics

from newrelic_telemetry_sdk import GaugeMetric, MetricClient

_NEWRELIC_BASE_HOST = "metric-api.eu.newrelic.com"


class NewRelicClient:
    def __init__(self, license_key: str):
        self.__client = MetricClient(license_key=license_key, host=_NEWRELIC_BASE_HOST)

    def send(self, metrics: UpcloudMetrics):
        batch = []

        for metric in metrics.metrics:
            for record in metric.records:
                batch.append(
                    GaugeMetric(
                        name=f"upcloud.db.{metric.metric_name}",
                        value=record.value,
                        tags={"host": record.label, "db_role": record.db_role},
                    )
                )

        response = self.__client.send_batch(batch)
        response.raise_for_status()
