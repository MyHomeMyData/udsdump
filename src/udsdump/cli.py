"""CLI entry point for udsdump."""

from __future__ import annotations

import argparse
import asyncio
import sys

from .formatter import json_line, text_line
from .monitor import UDSMonitor
from .uds import UDSTransaction


def _parse_id_pair(value: str) -> tuple[int, int]:
    """Parse 'REQ:RSP' or 'REQ-RSP' into (int, int)."""
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
    """Parse 'MIN:MAX' or 'MIN-MAX' into (int, int)."""
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
        raise argparse.ArgumentTypeError(f"ID range MIN must be <= MAX, got: {value!r}")
    return lo, hi


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

    # Behaviour
    p.add_argument(
        "--timeout", "-t", type=float, default=1.0,
        help="Response timeout in seconds (default: 1.0)",
    )

    # Output
    p.add_argument(
        "--json", action="store_true",
        help="Output one JSON object per line instead of text",
    )
    p.add_argument(
        "--payload", action="store_true",
        help="Include raw UDS payload bytes in output (hex)",
    )

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    formatter = json_line if args.json else text_line

    def on_transaction(tx: UDSTransaction) -> None:
        print(formatter(tx), flush=True)

    monitor = UDSMonitor(
        interface=args.interface,
        channel=args.channel,
        bitrate=args.bitrate,
        response_offset=args.response_offset,
        id_range=args.id_range,
        explicit_pairs=args.id_pairs,
        timeout=args.timeout,
        include_payload=args.payload,
    )
    monitor.on_transaction(on_transaction)

    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        sys.exit(0)
