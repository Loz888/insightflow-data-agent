from contextlib import contextmanager
from time import perf_counter
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from opentelemetry import trace


class Telemetry:
    def __init__(self):
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "insightflow_requests_total", "Finished requests", ["status"], registry=self.registry
        )
        self.retries = Counter(
            "insightflow_retries_total", "Bounded retries", ["stage"], registry=self.registry
        )
        self.active = Gauge("insightflow_active_runs", "In-process admitted requests", registry=self.registry)
        self.seconds = Histogram(
            "insightflow_stage_seconds", "Actual stage duration", ["stage"], registry=self.registry
        )
        self.tokens = Counter(
            "insightflow_model_tokens_total", "Known model tokens", ["kind"], registry=self.registry
        )
        self.unknown = Counter(
            "insightflow_usage_unknown_total",
            "HTTP attempts without trustworthy usage",
            registry=self.registry,
        )
        self.cost = Counter(
            "insightflow_reserved_usd_total",
            "Conservative reservations; not supplier bill",
            registry=self.registry,
        )
        self.tracer = trace.get_tracer("insightflow.v2")

    @contextmanager
    def stage(self, name, run_id):
        started = perf_counter()
        with self.tracer.start_as_current_span(name, attributes={"run.id": str(run_id)}):
            try:
                yield
            finally:
                self.seconds.labels(name).observe(perf_counter() - started)

    def render(self):
        return generate_latest(self.registry)
