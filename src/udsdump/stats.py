"""Statistics collection for UDS traffic monitoring.

BucketStats   – counters + latency for one time period
StatsCollector – receives UDSTransactions, maintains overall and interval buckets
                 with optional breakdown by ID pair and/or service name
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field

from .uds import UDSTransaction


# ---------------------------------------------------------------------------
# Latency statistics
# ---------------------------------------------------------------------------


class LatencyStats:
    """Running latency statistics for successful (ok) transactions."""

    def __init__(self) -> None:
        self._values: list[float] = []

    def add(self, ms: float) -> None:
        self._values.append(ms)

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def min_ms(self) -> float | None:
        return min(self._values) if self._values else None

    @property
    def max_ms(self) -> float | None:
        return max(self._values) if self._values else None

    @property
    def mean_ms(self) -> float | None:
        return sum(self._values) / len(self._values) if self._values else None

    @property
    def median_ms(self) -> float | None:
        if not self._values:
            return None
        s = sorted(self._values)
        n = len(s)
        return (s[n // 2 - 1] + s[n // 2]) / 2 if n % 2 == 0 else s[n // 2]

    @property
    def p95_ms(self) -> float | None:
        if not self._values:
            return None
        s = sorted(self._values)
        return s[min(int(0.95 * len(s)), len(s) - 1)]

    def copy(self) -> LatencyStats:
        c = LatencyStats()
        c._values = list(self._values)
        return c


# ---------------------------------------------------------------------------
# Per-bucket counters
# ---------------------------------------------------------------------------


class BucketStats:
    """Transaction counters and latency for one time bucket."""

    def __init__(self) -> None:
        self.total: int = 0
        self.ok: int = 0
        self.nrc: int = 0
        self.timeout: int = 0
        # nrc_code -> (nrc_name | None, count)
        self.nrc_codes: dict[int, tuple[str | None, int]] = {}
        self.pending_with_0x78: int = 0
        self.latency: LatencyStats = LatencyStats()

    def add(self, tx: UDSTransaction) -> None:
        self.total += 1
        if tx.status == "ok":
            self.ok += 1
            if tx.duration_ms is not None:
                self.latency.add(tx.duration_ms)
        elif tx.status == "nrc":
            self.nrc += 1
            if tx.nrc is not None:
                name, cnt = self.nrc_codes.get(tx.nrc, (tx.nrc_name, 0))
                self.nrc_codes[tx.nrc] = (name, cnt + 1)
        elif tx.status == "timeout":
            self.timeout += 1
        if tx.pending_count > 0:
            self.pending_with_0x78 += 1

    @property
    def failed(self) -> int:
        return self.nrc + self.timeout

    @property
    def success_rate(self) -> float | None:
        return (self.ok / self.total * 100) if self.total else None

    def reset(self) -> None:
        self.total = 0
        self.ok = 0
        self.nrc = 0
        self.timeout = 0
        self.nrc_codes = {}
        self.pending_with_0x78 = 0
        self.latency = LatencyStats()

    def copy(self) -> BucketStats:
        c = BucketStats()
        c.total = self.total
        c.ok = self.ok
        c.nrc = self.nrc
        c.timeout = self.timeout
        c.nrc_codes = dict(self.nrc_codes)
        c.pending_with_0x78 = self.pending_with_0x78
        c.latency = self.latency.copy()
        return c


# ---------------------------------------------------------------------------
# Snapshots (immutable views returned by StatsCollector)
# ---------------------------------------------------------------------------


@dataclass
class IntervalSnapshot:
    start: float
    end: float
    stats: BucketStats
    by_pair: dict[tuple[int, int], BucketStats]
    by_service: dict[str, BucketStats]

    @property
    def duration_s(self) -> float:
        return self.end - self.start


@dataclass
class OverallSnapshot:
    stats: BucketStats
    by_pair: dict[tuple[int, int], BucketStats]
    by_service: dict[str, BucketStats]


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class StatsCollector:
    """Receives UDSTransaction objects and accumulates statistics.

    Parameters
    ----------
    breakdown:
        List of dimensions to break down stats by.
        Valid values: "pair", "service".
    """

    def __init__(self, breakdown: list[str]) -> None:
        self._breakdown = breakdown
        self._overall = BucketStats()
        self._interval = BucketStats()
        self._interval_start: float = time.time()

        self._overall_by_pair: dict[tuple[int, int], BucketStats] = defaultdict(BucketStats)
        self._overall_by_service: dict[str, BucketStats] = defaultdict(BucketStats)
        self._interval_by_pair: dict[tuple[int, int], BucketStats] = defaultdict(BucketStats)
        self._interval_by_service: dict[str, BucketStats] = defaultdict(BucketStats)

    def add(self, tx: UDSTransaction) -> None:
        self._overall.add(tx)
        self._interval.add(tx)
        if "pair" in self._breakdown:
            key = (tx.request_id, tx.response_id)
            self._overall_by_pair[key].add(tx)
            self._interval_by_pair[key].add(tx)
        if "service" in self._breakdown:
            self._overall_by_service[tx.service_name].add(tx)
            self._interval_by_service[tx.service_name].add(tx)

    def snapshot_and_reset_interval(self, interval_end: float) -> IntervalSnapshot:
        """Return a snapshot of the current interval and reset its counters."""
        snap = IntervalSnapshot(
            start=self._interval_start,
            end=interval_end,
            stats=self._interval.copy(),
            by_pair={k: v.copy() for k, v in self._interval_by_pair.items()},
            by_service={k: v.copy() for k, v in self._interval_by_service.items()},
        )
        self._interval.reset()
        self._interval_by_pair.clear()
        self._interval_by_service.clear()
        self._interval_start = interval_end
        return snap

    def overall_snapshot(self) -> OverallSnapshot:
        return OverallSnapshot(
            stats=self._overall.copy(),
            by_pair={k: v.copy() for k, v in self._overall_by_pair.items()},
            by_service={k: v.copy() for k, v in self._overall_by_service.items()},
        )
