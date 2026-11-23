"""Bounded-cardinality Prometheus text metrics, with no tenant or user labels."""
from __future__ import annotations

import threading
from collections import defaultdict


class Metrics:
    _BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self):
        self._lock = threading.Lock()
        self._http_count: dict[tuple[str, str], int] = defaultdict(int)
        self._http_seconds: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._signals: dict[str, int] = defaultdict(int)

    def observe_http(self, method: str, route: str, status_code: int, duration_s: float) -> None:
        # FastAPI supplies route templates (e.g. /users/{user_id}), which bound
        # cardinality. Raw request paths may contain identifiers and are collapsed.
        safe_route = route if route.startswith("/") and ("{" in route or route.count("/") <= 2) else "/other"
        key = (method.upper()[:8], safe_route[:80])
        with self._lock:
            self._http_count[(key[0], f"{key[1]}|{status_code // 100}xx")] += 1
            self._http_seconds[key].append(max(0.0, duration_s))
            if len(self._http_seconds[key]) > 10000:
                del self._http_seconds[key][:5000]

    def increment(self, name: str, amount: int = 1) -> None:
        if not name.replace("_", "").isalnum():
            raise ValueError("metric name must be a static identifier")
        with self._lock:
            self._signals[name] += amount

    def render(self) -> str:
        lines = ["# TYPE finesse_http_requests_total counter"]
        with self._lock:
            counts = list(self._http_count.items())
            histograms = list(self._http_seconds.items())
            signals = list(self._signals.items())
        for (method, route_status), value in counts:
            route, status_class = route_status.rsplit("|", 1)
            lines.append(f'finesse_http_requests_total{{method="{method}",route="{route}",status="{status_class}"}} {value}')
        lines.append("# TYPE finesse_http_request_duration_seconds histogram")
        for (method, route), values in histograms:
            for bucket in self._BUCKETS:
                count = sum(value <= bucket for value in values)
                lines.append(f'finesse_http_request_duration_seconds_bucket{{method="{method}",route="{route}",le="{bucket:g}"}} {count}')
            lines.append(f'finesse_http_request_duration_seconds_bucket{{method="{method}",route="{route}",le="+Inf"}} {len(values)}')
            lines.append(f'finesse_http_request_duration_seconds_count{{method="{method}",route="{route}"}} {len(values)}')
            lines.append(f'finesse_http_request_duration_seconds_sum{{method="{method}",route="{route}"}} {sum(values):.6f}')
        for name, value in signals:
            lines.append(f"finesse_{name} {value}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
