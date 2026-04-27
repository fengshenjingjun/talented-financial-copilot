"""
In-memory metrics collector.
In production, ship to Prometheus / Grafana / DataDog.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


class MetricsCollector:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._latencies: dict[str, list[float]] = defaultdict(list)
        self._started = time.time()

    # ── Counters ───────────────────────────────────────────────────────────────

    def inc(self, key: str, value: int = 1) -> None:
        self._counters[key] += value

    def scene_hit(self, scene: str) -> None:
        self.inc(f"scene.{scene}.hits")

    def tool_called(self, tool: str, success: bool) -> None:
        self.inc(f"tool.{tool}.{'ok' if success else 'err'}")

    def risk_blocked(self, layer: str) -> None:
        self.inc(f"risk.{layer}.blocked")

    def error(self, node: str) -> None:
        self.inc(f"node.{node}.error")

    # ── Latencies ──────────────────────────────────────────────────────────────

    def record_latency(self, key: str, duration_ms: float) -> None:
        self._latencies[key].append(duration_ms)

    def p99(self, key: str) -> float | None:
        vals = sorted(self._latencies.get(key, []))
        if not vals:
            return None
        idx = max(0, int(len(vals) * 0.99) - 1)
        return vals[idx]

    def avg(self, key: str) -> float | None:
        vals = self._latencies.get(key, [])
        return sum(vals) / len(vals) if vals else None

    # ── Report ─────────────────────────────────────────────────────────────────

    def report(self) -> dict[str, Any]:
        uptime = round(time.time() - self._started, 1)
        latency_summary = {}
        for key, vals in self._latencies.items():
            latency_summary[key] = {
                "count": len(vals),
                "avg_ms": round(sum(vals) / len(vals), 2) if vals else 0,
                "p99_ms": round(self.p99(key) or 0, 2),
            }
        return {
            "uptime_seconds": uptime,
            "counters": dict(self._counters),
            "latency": latency_summary,
        }


metrics = MetricsCollector()
