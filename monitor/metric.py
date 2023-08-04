from dataclasses import dataclass
from typing import List


@dataclass
class UpcloudRecord:
    db_role: str
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
