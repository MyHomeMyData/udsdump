"""Transaction manager: ISO-TP assembly, UDS pairing, timeout tracking.

Stateful, I/O-free – all CAN frames are fed in via feed(); completed
transactions and timed-out requests are returned as UDSTransaction objects.

Parallelism: one ISOTPAssembler per monitored CAN ID.  Multiple simultaneous
conversations on different ID pairs are handled independently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .isotp import ISOTPAssembler
from .uds import DecodedUDS, UDSTransaction, decode


_NRC_PENDING = 0x78  # requestCorrectlyReceivedResponsePending


@dataclass
class _Pending:
    timestamp: float       # CAN hardware timestamp of the original request – for display
    deadline: float        # reset on every NRC 0x78; used for timeout calculation
    req_id: int
    rsp_id: int
    decoded: DecodedUDS
    req_frame_type: str
    req_length: int
    req_payload: bytes | None
    pending_count: int = 0  # number of NRC 0x78 received so far


class TransactionManager:
    """Manages ISO-TP assembly and UDS request/response pairing.

    Parameters
    ----------
    id_pairs:
        Mapping {request_can_id: response_can_id}.
    timeout:
        Seconds to wait for a response before declaring timeout.
    include_payload:
        When True, raw UDS payload bytes are stored in UDSTransaction.
    """

    def __init__(
        self,
        id_pairs: dict[int, int],
        timeout: float = 1.0,
        include_payload: bool = False,
    ) -> None:
        self._req_to_rsp: dict[int, int] = dict(id_pairs)
        self._rsp_to_req: dict[int, int] = {v: k for k, v in id_pairs.items()}
        self._timeout = timeout
        self._include_payload = include_payload

        all_ids = set(id_pairs.keys()) | set(id_pairs.values())
        self._assemblers: dict[int, ISOTPAssembler] = {
            can_id: ISOTPAssembler() for can_id in all_ids
        }
        self._pending: dict[int, _Pending] = {}

    @property
    def monitored_ids(self) -> frozenset[int]:
        return frozenset(self._assemblers)

    def feed(
        self, can_id: int, data: bytes, timestamp: float
    ) -> UDSTransaction | None:
        """Process one CAN frame.  Returns a completed UDSTransaction or None."""
        assembler = self._assemblers.get(can_id)
        if assembler is None:
            return None

        result = assembler.feed(data)
        if result is None:
            return None

        payload, frame_type = result
        decoded = decode(payload)
        if decoded is None:
            return None

        # Disambiguate IDs that appear in both req and rsp roles via the SID.
        is_req_id = can_id in self._req_to_rsp
        is_rsp_id = can_id in self._rsp_to_req

        if is_req_id and not decoded.is_response:
            return self._handle_request(can_id, decoded, frame_type, payload, timestamp)

        if is_rsp_id and decoded.is_response:
            return self._handle_response(can_id, decoded, frame_type, payload, timestamp)

        return None

    def _handle_request(
        self,
        req_id: int,
        decoded: DecodedUDS,
        frame_type: str,
        payload: bytes,
        timestamp: float,
    ) -> None:
        rsp_id = self._req_to_rsp[req_id]
        self._pending[req_id] = _Pending(
            timestamp=timestamp,
            deadline=timestamp,
            req_id=req_id,
            rsp_id=rsp_id,
            decoded=decoded,
            req_frame_type=frame_type,
            req_length=len(payload),
            req_payload=payload if self._include_payload else None,
        )
        return None

    def _handle_response(
        self,
        rsp_id: int,
        decoded: DecodedUDS,
        rsp_frame_type: str,
        payload: bytes,
        timestamp: float,
    ) -> UDSTransaction | None:
        req_id = self._rsp_to_req[rsp_id]

        # NRC 0x78: ECU needs more time – restart timeout, stay pending.
        if decoded.nrc == _NRC_PENDING:
            pending = self._pending.get(req_id)
            if pending is not None:
                pending.deadline = timestamp
                pending.pending_count += 1
            return None

        pending = self._pending.pop(req_id, None)
        if pending is None:
            return None

        status = "nrc" if decoded.service_id == 0x7F else "ok"
        duration_ms = (timestamp - pending.timestamp) * 1000

        return UDSTransaction(
            timestamp=pending.timestamp,
            request_id=req_id,
            response_id=rsp_id,
            service_id=pending.decoded.service_id,
            service_name=pending.decoded.service_name,
            req_frame_type=pending.req_frame_type,
            rsp_frame_type=rsp_frame_type,
            status=status,
            did=pending.decoded.did,
            sub_function=pending.decoded.sub_function,
            req_length=pending.req_length,
            rsp_length=len(payload),
            nrc=decoded.nrc,
            nrc_name=decoded.nrc_name,
            duration_ms=duration_ms,
            pending_count=pending.pending_count,
            req_payload=pending.req_payload,
            rsp_payload=payload if self._include_payload else None,
        )

    def check_timeouts(self, current_time: float | None = None) -> list[UDSTransaction]:
        """Return and remove all pending requests that have exceeded the timeout."""
        if current_time is None:
            current_time = time.time()

        expired = [
            req_id
            for req_id, p in self._pending.items()
            if current_time - p.deadline >= self._timeout
        ]
        transactions = []
        for req_id in expired:
            p = self._pending.pop(req_id)
            transactions.append(
                UDSTransaction(
                    timestamp=p.timestamp,
                    request_id=p.req_id,
                    response_id=p.rsp_id,
                    service_id=p.decoded.service_id,
                    service_name=p.decoded.service_name,
                    req_frame_type=p.req_frame_type,
                    rsp_frame_type=None,
                    status="timeout",
                    did=p.decoded.did,
                    sub_function=p.decoded.sub_function,
                    req_length=p.req_length,
                    rsp_length=0,
                    pending_count=p.pending_count,
                    req_payload=p.req_payload,
                )
            )
        return transactions
