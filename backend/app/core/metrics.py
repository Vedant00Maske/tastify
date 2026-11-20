"""Prometheus metrics (spec §15). Exposed at /metrics by the API and on WORKER_METRICS_PORT by the
Celery worker. Labels are low-cardinality on purpose: route templates, never raw paths or ids.
"""

from collections.abc import Iterator
from pathlib import Path

from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

# Latency buckets around the spec's 500 ms recommendation target.
_LATENCY = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)

# --- Application ---------------------------------------------------------------------------
HTTP_REQUESTS = Counter(
    "soniqueo_http_requests_total", "HTTP requests handled", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "soniqueo_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=_LATENCY,
)
HTTP_IN_FLIGHT = Gauge("soniqueo_http_requests_in_flight", "HTTP requests being handled")
DB_QUERY_LATENCY = Histogram(
    "soniqueo_db_query_duration_seconds",
    "Database statement latency",
    ["operation"],
    buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 10.0),
)
CACHE_REQUESTS = Counter(
    "soniqueo_cache_requests_total", "Cache lookups", ["cache", "result"]
)  # result: hit | miss
OVERLOADED = Counter(
    "soniqueo_overloaded_total", "Requests refused because every database connection was busy"
)
RATE_LIMITED = Counter("soniqueo_rate_limited_total", "Requests refused by a rate limit", ["limit"])
BACKGROUND_JOBS = Counter(
    "soniqueo_background_jobs_total", "Background job outcomes", ["task", "outcome"]
)  # outcome: success | failure | retry
PROVIDER_REQUESTS = Counter(
    "soniqueo_provider_requests_total", "Calls to external music services", ["provider", "outcome"]
)  # outcome: ok | rate_limited | error
EMAILS = Counter("soniqueo_emails_total", "Outgoing e-mails", ["kind", "outcome"])
CLIENT_ERRORS = Counter("soniqueo_client_errors_total", "Errors reported by the web app", ["kind"])

# --- Recommendations -----------------------------------------------------------------------
RECOMMENDATION_LATENCY = Histogram(
    "soniqueo_recommendation_stage_seconds",
    "Time spent per recommendation stage",
    ["surface", "stage"],  # stage: candidates | ranking | total
    buckets=_LATENCY,
)
RECOMMENDATION_CANDIDATES = Histogram(
    "soniqueo_recommendation_candidates",
    "Candidates retrieved per request",
    ["surface"],
    buckets=(0, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000),
)
RECOMMENDATIONS_SERVED = Counter(
    "soniqueo_recommendations_served_total",
    "Recommendation responses by surface and model version",
    ["surface", "model_version"],
)
RECOMMENDATION_ITEMS = Counter(
    "soniqueo_recommendation_items_total", "Recommended items returned", ["surface"]
)
FEEDBACK_EVENTS = Counter(
    "soniqueo_feedback_events_total", "Feedback events recorded", ["event_type", "attributed"]
)  # attributed: whether the event names the recommendation response it came from


def cache_lookup(cache: str, hit: bool) -> None:
    CACHE_REQUESTS.labels(cache, "hit" if hit else "miss").inc()


class BackupStatusCollector(Collector):
    """The time of the last successful database backup, read at scrape time from the file the
    backup job writes (infrastructure/backup/backup.sh). Absent file: 0, so the alert fires."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def collect(self) -> Iterator[GaugeMetricFamily]:
        try:
            value = float(self.path.read_text().strip())
        except (OSError, ValueError):
            value = 0.0
        family = GaugeMetricFamily(
            "soniqueo_backup_last_success_timestamp_seconds",
            "Unix time of the last successful database backup",
        )
        family.add_metric([], value)
        yield family


def register_backup_status(path: str) -> None:
    REGISTRY.register(BackupStatusCollector(path))
