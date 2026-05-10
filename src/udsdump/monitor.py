"""UDSMonitor: async CAN capture + transaction dispatch.

Wires together the CAN bus (python-can), the TransactionManager, and
caller-supplied callbacks or an async-generator interface.

Timeout checker runs as a separate asyncio task so it never blocks the
main receive loop, and multiple parallel conversations proceed independently.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable

import can

from .transaction import TransactionManager
from .uds import UDSTransaction


def _build_id_pairs(
    id_range: tuple[int, int],
    response_offset: int,
    explicit_pairs: list[tuple[int, int]] | None,
    ignore_req_ids: set[int] | None = None,
) -> dict[int, int]:
    """Return {req_id: rsp_id} from offset+range or explicit pairs."""
    ignore = ignore_req_ids or set()
    if explicit_pairs:
        return {req: rsp for req, rsp in explicit_pairs if req not in ignore}
    lo, hi = id_range
    return {req: req + response_offset for req in range(lo, hi + 1) if req not in ignore}


class UDSMonitor:
    """Async UDS traffic monitor.

    Parameters
    ----------
    interface:
        python-can interface name, e.g. "socketcan", "kvaser", "peak".
    channel:
        Interface channel, e.g. "vcan0", "can0".
    bitrate:
        CAN bus bitrate in bit/s (ignored by socketcan).
    response_offset:
        Default response ID offset (request ID + offset = response ID).
    id_range:
        (min, max) range of request CAN IDs to monitor.
    explicit_pairs:
        If provided, overrides id_range/response_offset.
        List of (request_id, response_id) tuples.
    timeout:
        Seconds to wait for a response before emitting a timeout transaction.
    include_payload:
        When True, raw UDS payload bytes are included in UDSTransaction.
    """

    def __init__(
        self,
        interface: str,
        channel: str,
        bitrate: int = 500_000,
        response_offset: int = 0x10,
        id_range: tuple[int, int] = (0x600, 0x6FF),
        explicit_pairs: list[tuple[int, int]] | None = None,
        ignore_req_ids: set[int] | None = None,
        timeout: float = 1.0,
        include_payload: bool = False,
    ) -> None:
        self._bus_kwargs = dict(interface=interface, channel=channel, bitrate=bitrate)
        self._timeout = timeout
        id_pairs = _build_id_pairs(id_range, response_offset, explicit_pairs, ignore_req_ids)
        self._manager = TransactionManager(
            id_pairs=id_pairs,
            timeout=timeout,
            include_payload=include_payload,
        )
        self._callbacks: list[Callable[[UDSTransaction], None]] = []

    def on_transaction(self, callback: Callable[[UDSTransaction], None]) -> None:
        """Register a callback invoked for each completed UDSTransaction."""
        self._callbacks.append(callback)

    def _emit(self, tx: UDSTransaction) -> None:
        for cb in self._callbacks:
            cb(tx)

    async def run(self) -> None:
        """Start monitoring. Blocks until cancelled."""
        bus = can.Bus(**self._bus_kwargs)
        reader = can.AsyncBufferedReader()
        notifier = can.Notifier(bus, [reader], loop=asyncio.get_event_loop())
        timeout_task = asyncio.create_task(self._timeout_loop())
        try:
            async for msg in reader:
                if msg.arbitration_id not in self._manager.monitored_ids:
                    continue
                tx = self._manager.feed(
                    msg.arbitration_id,
                    bytes(msg.data),
                    msg.timestamp,
                )
                if tx is not None:
                    self._emit(tx)
        finally:
            timeout_task.cancel()
            notifier.stop()
            bus.shutdown()

    async def _timeout_loop(self) -> None:
        """Check for timed-out requests every 100 ms."""
        while True:
            await asyncio.sleep(0.1)
            now = time.time()
            for tx in self._manager.check_timeouts(now):
                self._emit(tx)

    async def transactions(self) -> AsyncGenerator[UDSTransaction, None]:
        """Async generator yielding each completed UDSTransaction."""
        queue: asyncio.Queue[UDSTransaction] = asyncio.Queue()
        self.on_transaction(queue.put_nowait)
        run_task = asyncio.create_task(self.run())
        try:
            while True:
                yield await queue.get()
        finally:
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass
