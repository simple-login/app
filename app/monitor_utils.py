from app import metrics
from app.build_info import VERSION


def send_version_event(service: str):
    metrics.record_event("ServiceVersion", {"service": service, "version": VERSION})
