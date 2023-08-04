from dataclasses import dataclass
from typing import List


@dataclass
class UpcloudRecord:
    label: str
    time: str
    value: float


@dataclass
class UpcloudMetric:
    metric_name: str
    records: List[UpcloudRecord]


@dataclass
class UpcloudMetrics:
    metrics: List[UpcloudMetric]
