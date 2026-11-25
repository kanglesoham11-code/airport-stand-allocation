"""Operating counters and latency percentile (sections 10A.9 and 23.39).

Values live in memory and reset on restart. One lock covers the counters.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock

from stand_allocation import config


def p95_nearest_rank(durations: list[float]) -> float:
    """p95 over the last window using the nearest-rank method.

    rank = ceil(0.95 * n), counting from 1; returns sorted[rank - 1].
    n = 100 -> rank 95, n = 1000 -> rank 950 (section 10A.9 / 23.39).
    """
    n = len(durations)
    if n == 0:
        return 0.0
    sorted_durations = sorted(durations)
    rank = (config.LATENCY_PERCENTILE * n + config.PERCENT_SCALE - 1) // config.PERCENT_SCALE
    rank = max(1, min(rank, n))
    return sorted_durations[rank - 1]


class OpsCounters:
    """In-memory request and latency counters."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._start_time = time.monotonic()
        self._requests_total: dict[str, int] = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
        self._rate_limited_total = 0
        self._auth_failed_total = 0
        self._latencies: deque[float] = deque(maxlen=config.LATENCY_WINDOW)

    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def record_request(self, status_class: str, latency_seconds: float) -> None:
        with self._lock:
            self._requests_total[status_class] = (
                self._requests_total.get(status_class, 0) + 1
            )
            self._latencies.append(latency_seconds)

    def record_rate_limited(self) -> None:
        with self._lock:
            self._rate_limited_total += 1

    def record_auth_failed(self) -> None:
        with self._lock:
            self._auth_failed_total += 1

    def snapshot(self, run_id: str | None) -> dict:
        with self._lock:
            latencies = list(self._latencies)
        return {
            "uptime_seconds": self.uptime_seconds(),
            "run_id": run_id,
            "requests_total": dict(self._requests_total),
            "rate_limited_total": self._rate_limited_total,
            "auth_failed_total": self._auth_failed_total,
            "latency_p95_ms": p95_nearest_rank(latencies) * 1000.0,
        }



