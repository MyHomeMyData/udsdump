"""Formatters for statistics output (always written to stderr).

format_interval()  – one fixed time slice
format_summary()   – overall summary printed on exit
"""

from __future__ import annotations

import datetime

from .stats import BucketStats, IntervalSnapshot, LatencyStats, OverallSnapshot

_WIDTH = 80


def _sep(char: str) -> str:
    return char * _WIDTH


def _fmt_ms(ms: float | None) -> str:
    if ms is None:
        return "–"
    return f"{ms:.1f}ms"


def _fmt_latency(lat: LatencyStats) -> str:
    if lat.count == 0:
        return "–"
    parts = [
        f"min={_fmt_ms(lat.min_ms)}",
        f"mean={_fmt_ms(lat.mean_ms)}",
        f"median={_fmt_ms(lat.median_ms)}",
        f"p95={_fmt_ms(lat.p95_ms)}",
        f"max={_fmt_ms(lat.max_ms)}",
    ]
    return "  ".join(parts)


def _fmt_bucket_lines(stats: BucketStats, rate: float | None = None) -> list[str]:
    lines = []
    rate_str = f"  rate={rate:.2f}/s" if rate is not None else ""
    sr = f"  success={stats.success_rate:.1f}%" if stats.success_rate is not None else ""
    lines.append(
        f"Transactions   total={stats.total:<5}  ok={stats.ok:<5}  "
        f"nrc={stats.nrc:<4}  timeout={stats.timeout}{rate_str}{sr}"
    )
    if stats.nrc_codes:
        parts = "  ".join(
            f"{name or f'0x{code:02X}'}={cnt}"
            for code, (name, cnt) in sorted(stats.nrc_codes.items())
        )
        lines.append(f"  NRC            {parts}")
    if stats.pending_with_0x78:
        lines.append(f"  Pending 0x78   {stats.pending_with_0x78} transaction(s)")
    lines.append(f"Latency (ok)   {_fmt_latency(stats.latency)}")
    return lines


def _fmt_by_pair(by_pair: dict[tuple[int, int], BucketStats]) -> list[str]:
    if not by_pair:
        return []
    lines = ["By ID pair:"]
    for (req, rsp), s in sorted(by_pair.items()):
        lat = _fmt_latency(s.latency) if s.latency.count else "–"
        lines.append(
            f"  0x{req:04X}→0x{rsp:04X}   "
            f"ok={s.ok:<4}  nrc={s.nrc:<3}  timeout={s.timeout:<3}   {lat}"
        )
    return lines


def _fmt_by_service(by_service: dict[str, BucketStats]) -> list[str]:
    if not by_service:
        return []
    lines = ["By service:"]
    w = max(len(svc) for svc in by_service) + 2
    for svc, s in sorted(by_service.items()):
        lat = _fmt_latency(s.latency) if s.latency.count else "–"
        lines.append(
            f"  {svc:<{w}}  ok={s.ok:<4}  nrc={s.nrc:<3}  timeout={s.timeout:<3}   {lat}"
        )
    return lines


def format_interval(snap: IntervalSnapshot, breakdown: list[str]) -> str:
    t0 = datetime.datetime.fromtimestamp(snap.start).strftime("%H:%M:%S")
    t1 = datetime.datetime.fromtimestamp(snap.end).strftime("%H:%M:%S")
    dur = int(snap.duration_s)
    rate = snap.stats.total / snap.duration_s if snap.duration_s > 0 else None

    lines = [
        _sep("─"),
        f"Stats [{t0} – {t1}] ({dur}s)",
    ]
    lines.extend(_fmt_bucket_lines(snap.stats, rate))
    if "pair" in breakdown:
        lines.extend(_fmt_by_pair(snap.by_pair))
    if "service" in breakdown:
        lines.extend(_fmt_by_service(snap.by_service))
    lines.append(_sep("─"))
    return "\n".join(lines)


def format_summary(snap: OverallSnapshot, runtime_s: float, breakdown: list[str]) -> str:
    h, rem = divmod(int(runtime_s), 3600)
    m, s = divmod(rem, 60)
    if h:
        dur_str = f"{h}h {m}m {s}s"
    elif m:
        dur_str = f"{m}m {s}s"
    else:
        dur_str = f"{s}s"
    rate = snap.stats.total / runtime_s if runtime_s > 0 else None

    lines = [
        _sep("═"),
        f"Summary (runtime: {dur_str})",
    ]
    lines.extend(_fmt_bucket_lines(snap.stats, rate))
    if "pair" in breakdown:
        lines.extend(_fmt_by_pair(snap.by_pair))
    if "service" in breakdown:
        lines.extend(_fmt_by_service(snap.by_service))
    lines.append(_sep("═"))
    return "\n".join(lines)
