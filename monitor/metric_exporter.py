from app.config import UPCLOUD_DB_ID, UPCLOUD_PASSWORD, UPCLOUD_USERNAME
from app.log import LOG
from monitor.newrelic import NewRelicClient
from monitor.upcloud import UpcloudClient


class MetricExporter:
    def __init__(self, newrelic_license: str):
        self.__upcloud = UpcloudClient(
            username=UPCLOUD_USERNAME, password=UPCLOUD_PASSWORD
        )
        self.__newrelic = NewRelicClient(newrelic_license)

    def run(self):
        try:
            metrics = self.__upcloud.get_metrics(UPCLOUD_DB_ID)
            self.__newrelic.send(metrics)
            LOG.info("Upcloud metrics sent to NewRelic")
        except Exception as e:
            LOG.warning(f"Could not export metrics: {e}")
