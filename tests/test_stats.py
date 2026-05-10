"""Tests for StatsCollector and LatencyStats."""

import pytest
from udsdump.stats import BucketStats, LatencyStats, StatsCollector
from udsdump.uds import UDSTransaction


def _tx(
    status: str = "ok",
    duration_ms: float | None = 10.0,
    request_id: int = 0x680,
    response_id: int = 0x690,
    service_name: str = "ReadDataByIdentifier",
    service_id: int = 0x22,
    nrc: int | None = None,
    nrc_name: str | None = None,
    pending_count: int = 0,
) -> UDSTransaction:
    return UDSTransaction(
        timestamp=1000.0,
        request_id=request_id,
        response_id=response_id,
        service_id=service_id,
        service_name=service_name,
        req_frame_type="SF",
        rsp_frame_type="SF" if status != "timeout" else None,
        status=status,
        duration_ms=duration_ms,
        nrc=nrc,
        nrc_name=nrc_name,
        pending_count=pending_count,
    )


class TestLatencyStats:
    def test_empty(self):
        lat = LatencyStats()
        assert lat.count == 0
        assert lat.min_ms is None
        assert lat.max_ms is None
        assert lat.mean_ms is None
        assert lat.median_ms is None
        assert lat.p95_ms is None

    def test_single_value(self):
        lat = LatencyStats()
        lat.add(42.0)
        assert lat.count == 1
        assert lat.min_ms == 42.0
        assert lat.max_ms == 42.0
        assert lat.mean_ms == 42.0
        assert lat.median_ms == 42.0
        assert lat.p95_ms == 42.0

    def test_mean(self):
        lat = LatencyStats()
        for v in [10.0, 20.0, 30.0]:
            lat.add(v)
        assert lat.mean_ms == pytest.approx(20.0)

    def test_median_odd(self):
        lat = LatencyStats()
        for v in [5.0, 1.0, 3.0]:
            lat.add(v)
        assert lat.median_ms == pytest.approx(3.0)

    def test_median_even(self):
        lat = LatencyStats()
        for v in [1.0, 2.0, 3.0, 4.0]:
            lat.add(v)
        assert lat.median_ms == pytest.approx(2.5)

    def test_p95(self):
        lat = LatencyStats()
        for v in range(1, 21):  # 1..20
            lat.add(float(v))
        # 95th percentile index = int(0.95 * 20) = 19 → sorted[19] = 20
        assert lat.p95_ms == pytest.approx(20.0)

    def test_copy_is_independent(self):
        lat = LatencyStats()
        lat.add(10.0)
        c = lat.copy()
        lat.add(99.0)
        assert c.count == 1
        assert c.max_ms == pytest.approx(10.0)


class TestBucketStats:
    def test_ok_transaction(self):
        b = BucketStats()
        b.add(_tx(status="ok", duration_ms=15.0))
        assert b.total == 1
        assert b.ok == 1
        assert b.nrc == 0
        assert b.timeout == 0
        assert b.latency.count == 1
        assert b.latency.mean_ms == pytest.approx(15.0)

    def test_nrc_transaction(self):
        b = BucketStats()
        b.add(_tx(status="nrc", duration_ms=8.0, nrc=0x22, nrc_name="conditionsNotCorrect"))
        assert b.nrc == 1
        assert 0x22 in b.nrc_codes
        assert b.nrc_codes[0x22] == ("conditionsNotCorrect", 1)
        assert b.latency.count == 0  # NRC latency not tracked

    def test_nrc_accumulates(self):
        b = BucketStats()
        b.add(_tx(status="nrc", nrc=0x22, nrc_name="conditionsNotCorrect"))
        b.add(_tx(status="nrc", nrc=0x22, nrc_name="conditionsNotCorrect"))
        b.add(_tx(status="nrc", nrc=0x35, nrc_name="invalidKey"))
        assert b.nrc_codes[0x22][1] == 2
        assert b.nrc_codes[0x35][1] == 1

    def test_timeout_transaction(self):
        b = BucketStats()
        b.add(_tx(status="timeout", duration_ms=None))
        assert b.timeout == 1
        assert b.latency.count == 0

    def test_pending_0x78_counted(self):
        b = BucketStats()
        b.add(_tx(pending_count=0))
        b.add(_tx(pending_count=2))
        assert b.pending_with_0x78 == 1

    def test_success_rate(self):
        b = BucketStats()
        b.add(_tx(status="ok"))
        b.add(_tx(status="ok"))
        b.add(_tx(status="timeout", duration_ms=None))
        assert b.success_rate == pytest.approx(200 / 3)

    def test_success_rate_empty(self):
        assert BucketStats().success_rate is None

    def test_reset(self):
        b = BucketStats()
        b.add(_tx(status="ok"))
        b.add(_tx(status="nrc", nrc=0x22))
        b.reset()
        assert b.total == 0
        assert b.ok == 0
        assert b.nrc_codes == {}
        assert b.latency.count == 0

    def test_copy_is_independent(self):
        b = BucketStats()
        b.add(_tx(status="ok", duration_ms=10.0))
        c = b.copy()
        b.add(_tx(status="timeout", duration_ms=None))
        assert c.total == 1
        assert c.timeout == 0


class TestStatsCollector:
    def test_add_updates_overall_and_interval(self):
        col = StatsCollector([])
        col.add(_tx(status="ok"))
        col.add(_tx(status="nrc", nrc=0x22))
        assert col._overall.total == 2
        assert col._interval.total == 2

    def test_snapshot_and_reset_clears_interval(self):
        col = StatsCollector([])
        col.add(_tx(status="ok"))
        col.add(_tx(status="ok"))
        snap = col.snapshot_and_reset_interval(1000.0 + 60.0)
        assert snap.stats.total == 2
        assert col._interval.total == 0
        assert col._overall.total == 2  # overall unchanged

    def test_interval_snapshot_start_and_end(self):
        col = StatsCollector([])
        col._interval_start = 1000.0
        snap = col.snapshot_and_reset_interval(1060.0)
        assert snap.start == pytest.approx(1000.0)
        assert snap.end == pytest.approx(1060.0)
        assert snap.duration_s == pytest.approx(60.0)

    def test_subsequent_intervals_accumulate_correctly(self):
        col = StatsCollector([])
        col.add(_tx(status="ok"))
        col.snapshot_and_reset_interval(1060.0)
        col.add(_tx(status="timeout", duration_ms=None))
        col.add(_tx(status="timeout", duration_ms=None))
        snap2 = col.snapshot_and_reset_interval(1120.0)
        assert snap2.stats.total == 2
        assert snap2.stats.timeout == 2
        assert col._overall.total == 3  # 1 ok + 2 timeout

    def test_breakdown_by_pair(self):
        col = StatsCollector(["pair"])
        col.add(_tx(request_id=0x680, response_id=0x690, status="ok"))
        col.add(_tx(request_id=0x6A0, response_id=0x6B0, status="ok"))
        col.add(_tx(request_id=0x680, response_id=0x690, status="nrc", nrc=0x22))
        snap = col.overall_snapshot()
        assert (0x680, 0x690) in snap.by_pair
        assert (0x6A0, 0x6B0) in snap.by_pair
        assert snap.by_pair[(0x680, 0x690)].total == 2
        assert snap.by_pair[(0x6A0, 0x6B0)].total == 1

    def test_breakdown_by_service(self):
        col = StatsCollector(["service"])
        col.add(_tx(service_name="ReadDataByIdentifier", status="ok"))
        col.add(_tx(service_name="TesterPresent", status="ok"))
        col.add(_tx(service_name="ReadDataByIdentifier", status="ok"))
        snap = col.overall_snapshot()
        assert snap.by_service["ReadDataByIdentifier"].total == 2
        assert snap.by_service["TesterPresent"].total == 1

    def test_breakdown_both(self):
        col = StatsCollector(["pair", "service"])
        col.add(_tx(request_id=0x680, response_id=0x690,
                    service_name="TesterPresent", status="ok"))
        snap = col.overall_snapshot()
        assert (0x680, 0x690) in snap.by_pair
        assert "TesterPresent" in snap.by_service

    def test_no_breakdown_when_not_requested(self):
        col = StatsCollector([])
        col.add(_tx(status="ok"))
        snap = col.overall_snapshot()
        assert snap.by_pair == {}
        assert snap.by_service == {}

    def test_interval_breakdown_resets(self):
        col = StatsCollector(["pair"])
        col.add(_tx(request_id=0x680, response_id=0x690, status="ok"))
        col.snapshot_and_reset_interval(1060.0)
        # Second interval: different pair
        col.add(_tx(request_id=0x6A0, response_id=0x6B0, status="ok"))
        snap2 = col.snapshot_and_reset_interval(1120.0)
        assert (0x680, 0x690) not in snap2.by_pair
        assert (0x6A0, 0x6B0) in snap2.by_pair
