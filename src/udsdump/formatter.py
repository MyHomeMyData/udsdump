"""Output formatters for UDSTransaction objects.

text_line()  – one fixed-width text line per transaction (default)
json_line()  – one JSON object per transaction (--json flag)

One line per complete transaction (REQ + RSP combined).
"""

from __future__ import annotations

import datetime
import json

from .uds import UDSTransaction

_SERVICE_NAME_WIDTH = 28


def _frame_type_str(tx: UDSTransaction) -> str:
    """Return 'SF/SF', 'SF/MF', 'MF/SF', 'MF/MF', or 'MF' / 'SF' on timeout."""
    if tx.rsp_frame_type is None:
        return tx.req_frame_type
    return f"{tx.req_frame_type}/{tx.rsp_frame_type}"


def text_line(tx: UDSTransaction) -> str:
    """Format a UDSTransaction as a single human-readable line."""
    dt_obj = datetime.datetime.fromtimestamp(tx.timestamp)
    ts = dt_obj.strftime("%H:%M:%S.") + f"{dt_obj.microsecond // 1000:03d}"

    id_pair = f"0x{tx.request_id:04X}→0x{tx.response_id:04X}"

    svc = tx.service_name.ljust(_SERVICE_NAME_WIDTH)

    extra = ""
    if tx.did is not None:
        extra = f"DID=0x{tx.did:04X} ({tx.did})"
    elif tx.sub_function is not None:
        extra = f"sub=0x{tx.sub_function:02X}"
    extra = extra.ljust(20)

    lengths = f"req=0x{tx.req_length:02X} rsp=0x{tx.rsp_length:02X}"

    if tx.duration_ms is not None:
        dt_str = f"dt={tx.duration_ms:.1f}ms"
    else:
        dt_str = ""
    dt_str = dt_str.ljust(12)

    frame_type = _frame_type_str(tx)

    status_parts = [frame_type, tx.status]
    if tx.status == "nrc" and tx.nrc is not None:
        nrc_label = tx.nrc_name or ""
        status_parts.append(f"NRC=0x{tx.nrc:02X}({nrc_label})")
    if tx.pending_count:
        status_parts.append(f"pending×{tx.pending_count}")

    status_str = "  ".join(status_parts)

    payload_str = ""
    if tx.req_payload is not None or tx.rsp_payload is not None:
        parts = []
        if tx.req_payload is not None:
            parts.append(f"req_data={tx.req_payload.hex()}")
        if tx.rsp_payload is not None:
            parts.append(f"rsp_data={tx.rsp_payload.hex()}")
        payload_str = "  " + "  ".join(parts)

    return f"{ts}  {id_pair}  {svc}  {extra}  {lengths}  {dt_str}  {status_str}{payload_str}"


def json_line(tx: UDSTransaction) -> str:
    """Format a UDSTransaction as a JSON object (only set fields)."""
    obj: dict = {
        "timestamp": tx.timestamp,
        "request_id": tx.request_id,
        "response_id": tx.response_id,
        "service_id": tx.service_id,
        "service_name": tx.service_name,
        "req_frame_type": tx.req_frame_type,
        "status": tx.status,
    }
    if tx.rsp_frame_type is not None:
        obj["rsp_frame_type"] = tx.rsp_frame_type
    if tx.did is not None:
        obj["did"] = tx.did
    if tx.sub_function is not None:
        obj["sub_function"] = tx.sub_function
    if tx.req_length:
        obj["req_length"] = tx.req_length
    if tx.rsp_length:
        obj["rsp_length"] = tx.rsp_length
    if tx.nrc is not None:
        obj["nrc"] = tx.nrc
    if tx.nrc_name is not None:
        obj["nrc_name"] = tx.nrc_name
    if tx.duration_ms is not None:
        obj["duration_ms"] = round(tx.duration_ms, 3)
    if tx.pending_count:
        obj["pending_count"] = tx.pending_count
    if tx.req_payload is not None:
        obj["req_payload"] = tx.req_payload.hex()
    if tx.rsp_payload is not None:
        obj["rsp_payload"] = tx.rsp_payload.hex()
    return json.dumps(obj)
