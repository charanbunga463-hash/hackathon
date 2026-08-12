"""Minimal Prometheus-compatible metrics.

Written by hand rather than pulling in `prometheus_client`, because the whole
surface needed here is counters, gauges and histograms with a text exposition
format — about 150 lines — and a deployment dependency is a real cost.

Histogram buckets are chosen for this workload: sub-second API reads at one end,
multi-minute repair jobs at the other.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
JOB_BUCKETS = (0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0)

Labels = tuple[tuple[str, str], ...]


def _labels(**kwargs: str) -> Labels:
    return tuple(sorted((key, str(value)) for key, value in kwargs.items()))


def _render_labels(labels: Labels, extra: dict[str, str] | None = None) -> str:
    pairs = {key: value for key, value in labels}
    if extra:
        pairs.update(extra)
    if not pairs:
        return ""
    inner = ",".join(f'{key}="{_escape(value)}"' for key, value in sorted(pairs.items()))
    return f"{{{inner}}}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


@dataclass
class Counter:
    name: str
    help: str
    values: dict[Labels, float] = field(default_factory=lambda: defaultdict(float))

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self.values[_labels(**labels)] += amount

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        for labels, value in sorted(self.values.items()):
            lines.append(f"{self.name}{_render_labels(labels)} {value:g}")
        return lines


@dataclass
class Gauge:
    name: str
    help: str
    values: dict[Labels, float] = field(default_factory=lambda: defaultdict(float))

    def set(self, value: float, **labels: str) -> None:
        self.values[_labels(**labels)] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        self.values[_labels(**labels)] += amount

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} gauge"]
        for labels, value in sorted(self.values.items()):
            lines.append(f"{self.name}{_render_labels(labels)} {value:g}")
        return lines


@dataclass
class Histogram:
    name: str
    help: str
    buckets: tuple[float, ...] = LATENCY_BUCKETS
    counts: dict[Labels, list[int]] = field(default_factory=dict)
    sums: dict[Labels, float] = field(default_factory=lambda: defaultdict(float))
    totals: dict[Labels, int] = field(default_factory=lambda: defaultdict(int))

    def observe(self, value: float, **labels: str) -> None:
        key = _labels(**labels)
        if key not in self.counts:
            self.counts[key] = [0] * len(self.buckets)
        for index, upper in enumerate(self.buckets):
            if value <= upper:
                self.counts[key][index] += 1
        self.sums[key] += value
        self.totals[key] += 1

    def render(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key in sorted(self.counts):
            cumulative = 0
            for index, upper in enumerate(self.buckets):
                cumulative = self.counts[key][index]
                lines.append(
                    f"{self.name}_bucket{_render_labels(key, {'le': _fmt(upper)})} {cumulative}"
                )
            lines.append(
                f"{self.name}_bucket{_render_labels(key, {'le': '+Inf'})} {self.totals[key]}"
            )
            lines.append(f"{self.name}_sum{_render_labels(key)} {self.sums[key]:g}")
            lines.append(f"{self.name}_count{_render_labels(key)} {self.totals[key]}")
        return lines


def _fmt(value: float) -> str:
    return f"{value:g}"


class Registry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = time.time()

        self.http_requests = Counter(
            "apidoctor_http_requests_total", "HTTP requests by method, path and status."
        )
        self.http_latency = Histogram(
            "apidoctor_http_request_duration_seconds", "HTTP request latency.", LATENCY_BUCKETS
        )
        self.http_in_flight = Gauge(
            "apidoctor_http_in_flight", "HTTP requests currently being served."
        )
        self.rate_limited = Counter(
            "apidoctor_rate_limited_total", "Requests rejected by the rate limiter."
        )
        self.jobs = Counter("apidoctor_jobs_total", "Jobs by kind and terminal status.")
        self.job_duration = Histogram(
            "apidoctor_job_duration_seconds", "Job wall-clock duration.", JOB_BUCKETS
        )
        self.job_queue_depth = Gauge("apidoctor_job_queue_depth", "Jobs waiting for a slot.")
        self.job_running = Gauge("apidoctor_jobs_running", "Jobs currently executing.")
        self.job_rejected = Counter(
            "apidoctor_jobs_rejected_total", "Jobs refused by admission control."
        )
        self.sandbox_runs = Counter(
            "apidoctor_sandbox_runs_total", "Sandboxed executions by runner and outcome."
        )
        self.sandbox_duration = Histogram(
            "apidoctor_sandbox_duration_seconds", "Sandboxed execution duration.", JOB_BUCKETS
        )
        self.repairs = Counter("apidoctor_repairs_total", "Repair sessions by verdict.")
        self.ai_calls = Counter("apidoctor_ai_calls_total", "OpenAI calls by stage and outcome.")
        self.ai_tokens = Counter("apidoctor_ai_tokens_total", "OpenAI tokens by direction.")
        self.sse_clients = Gauge("apidoctor_sse_clients", "Connected SSE clients.")
        self.build_info = Gauge("apidoctor_build_info", "Build and runtime metadata.")

        self._all = [
            self.http_requests, self.http_latency, self.http_in_flight, self.rate_limited,
            self.jobs, self.job_duration, self.job_queue_depth, self.job_running,
            self.job_rejected, self.sandbox_runs, self.sandbox_duration, self.repairs,
            self.ai_calls, self.ai_tokens, self.sse_clients, self.build_info,
        ]

    def render(self) -> str:
        with self._lock:
            lines: list[str] = [
                "# HELP apidoctor_uptime_seconds Seconds since this worker started.",
                "# TYPE apidoctor_uptime_seconds gauge",
                f"apidoctor_uptime_seconds {time.time() - self.started_at:g}",
            ]
            for metric in self._all:
                lines.extend(metric.render())
            return "\n".join(lines) + "\n"


_registry: Registry | None = None


def get_metrics() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry


def reset_metrics() -> None:
    global _registry
    _registry = None
