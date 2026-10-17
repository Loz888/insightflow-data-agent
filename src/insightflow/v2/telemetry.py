from contextlib import contextmanager
from time import perf_counter
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from collections import deque
from threading import Lock
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult, SimpleSpanProcessor


class BoundedExporter(SpanExporter):
    def __init__(self):
        self.spans = deque(maxlen=2000)
        self.lock = Lock()

    def export(self, spans):
        with self.lock:
            for span in spans:
                self.spans.append(
                    {
                        "name": span.name,
                        "trace_id": format(span.context.trace_id, "032x"),
                        "span_id": format(span.context.span_id, "016x"),
                        "run_id": span.attributes.get("run.id"),
                        "duration_ms": (span.end_time - span.start_time) / 1000000,
                        "status": span.status.status_code.name,
                    }
                )
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def for_run(self, rid):
        with self.lock:
            return [s for s in self.spans if s["run_id"] == str(rid)]


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
        self.pool_wait = Gauge(
            "insightflow_pool_wait_seconds",
            "Cumulative actual psycopg pool wait",
            ["pool"],
            registry=self.registry,
        )
        self.pool_waiting = Gauge(
            "insightflow_pool_waiting",
            "Actual queued psycopg pool borrowers",
            ["pool"],
            registry=self.registry,
        )
        self.exporter = BoundedExporter()
        self.trace_provider = TracerProvider()
        self.trace_provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.trace_provider.get_tracer("insightflow.v2")

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
