"""CLI entry point for udsdump."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from .formatter import json_line, text_line
from .monitor import UDSMonitor
from .stats import StatsCollector
from .stats_formatter import format_interval, format_summary
from .uds import UDSTransaction


def _parse_id_pair(value: str) -> tuple[int, int]:
    sep = ":" if ":" in value else "-"
    parts = value.split(sep)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"ID pair must be REQ:RSP (hex), got: {value!r}"
        )
    try:
        return int(parts[0], 16), int(parts[1], 16)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"ID pair values must be hex integers, got: {value!r}"
        )


def _parse_id_range(value: str) -> tuple[int, int]:
    sep = ":" if ":" in value else "-"
    parts = value.split(sep)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"ID range must be MIN:MAX (hex), got: {value!r}"
        )
    try:
        lo, hi = int(parts[0], 16), int(parts[1], 16)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"ID range values must be hex integers, got: {value!r}"
        )
    if lo > hi:
        raise argparse.ArgumentTypeError(
            f"ID range MIN must be <= MAX, got: {value!r}"
        )
    return lo, hi


def _parse_ignore_requesters(value: str | None) -> set[int]:
    if not value:
        return set()
    result = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            result.add(int(part, 16))
        except ValueError:
            raise SystemExit(
                f"error: --ignore-requesters value {part!r} is not a valid hex integer"
            )
    return result


def _parse_breakdown(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [p.strip().lower() for p in value.split(",")]
    for p in parts:
        if p not in {"pair", "service"}:
            raise SystemExit(
                f"error: invalid --stats-breakdown key {p!r}. "
                "Valid values: pair, service"
            )
    return parts


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="udsdump",
        description=(
            "Monitor UDS-on-CAN traffic at the service level. "
            "One line per UDS transaction."
        ),
    )

    # CAN bus
    p.add_argument("--interface", "-i", default="socketcan",
                   help="python-can interface (default: socketcan)")
    p.add_argument("--channel", "-c", default="vcan0",
                   help="CAN channel (default: vcan0)")
    p.add_argument("--bitrate", "-b", type=int, default=500_000,
                   help="CAN bitrate in bit/s (default: 500000)")

    # ID pair strategy (mutually exclusive)
    id_group = p.add_mutually_exclusive_group()
    id_group.add_argument(
        "--id-pair", metavar="REQ:RSP", action="append", dest="id_pairs",
        type=_parse_id_pair,
        help="Explicit request:response ID pair (hex). May be repeated.",
    )
    id_group.add_argument(
        "--response-offset", metavar="OFFSET", type=lambda x: int(x, 16),
        default=0x10,
        help="Response ID = request ID + OFFSET (hex, default: 0x10)",
    )
    p.add_argument(
        "--id-range", metavar="MIN:MAX", type=_parse_id_range,
        default=(0x600, 0x6FF),
        help="CAN ID range to monitor (hex, default: 0x600:0x6FF). "
             "Ignored when --id-pair is used.",
    )

    p.add_argument(
        "--ignore-requesters", metavar="IDS",
        help="Comma-separated hex CAN IDs to ignore as requesters "
             "(e.g. 0x691,0x696). "
             "Frames from these IDs are not tracked.",
    )

    # Behaviour
    p.add_argument(
        "--timeout", "-t", type=float, default=1.0,
        help="Response timeout in seconds (default: 1.0)",
    )

    # Transaction output
    p.add_argument("--json", action="store_true",
                   help="Output one JSON object per line instead of text")
    p.add_argument("--payload", action="store_true",
                   help="Include raw UDS payload bytes in output (hex)")
    p.add_argument(
        "--no-transactions", action="store_true",
        help="Suppress per-transaction output (statistics only)",
    )

    # Statistics
    p.add_argument(
        "--stats-interval", metavar="N", type=float,
        help="Print periodic statistics every N seconds",
    )
    p.add_argument(
        "--stats-breakdown", metavar="KEY",
        help="Break down statistics by: pair, service, or pair,service",
    )

    return p


async def _periodic_stats(
    collector: StatsCollector,
    interval_s: float,
    breakdown: list[str],
) -> None:
    while True:
        await asyncio.sleep(interval_s)
        snap = collector.snapshot_and_reset_interval(time.time())
        print(format_interval(snap, breakdown), file=sys.stderr, flush=True)


async def _run(
    monitor: UDSMonitor,
    collector: StatsCollector | None,
    stats_interval: float | None,
    breakdown: list[str],
) -> None:
    tasks: list[asyncio.Task] = [asyncio.create_task(monitor.run())]
    if collector is not None and stats_interval:
        tasks.append(
            asyncio.create_task(_periodic_stats(collector, stats_interval, breakdown))
        )
    await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    breakdown = _parse_breakdown(args.stats_breakdown)
    ignore_req_ids = _parse_ignore_requesters(args.ignore_requesters)
    stats_enabled = bool(args.no_transactions or args.stats_interval or breakdown)
    collector = StatsCollector(breakdown) if stats_enabled else None

    fmt = json_line if args.json else text_line

    monitor = UDSMonitor(
        interface=args.interface,
        channel=args.channel,
        bitrate=args.bitrate,
        response_offset=args.response_offset,
        id_range=args.id_range,
        explicit_pairs=args.id_pairs,
        ignore_req_ids=ignore_req_ids,
        timeout=args.timeout,
        include_payload=args.payload,
    )

    if not args.no_transactions:
        monitor.on_transaction(lambda tx: print(fmt(tx), flush=True))
    if collector is not None:
        monitor.on_transaction(collector.add)

    t_start = time.time()
    try:
        asyncio.run(_run(monitor, collector, args.stats_interval, breakdown))
    except KeyboardInterrupt:
        pass
    finally:
        if collector is not None:
            snap = collector.overall_snapshot()
            runtime = time.time() - t_start
            print(
                format_summary(snap, runtime, breakdown),
                file=sys.stderr,
                flush=True,
            )
    sys.exit(0)
