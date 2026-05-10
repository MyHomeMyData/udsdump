"""UDS service decoder and transaction data model.

Decodes reassembled ISO-TP payloads at the UDS service level.
No payload bytes are decoded – only metadata (SID, DID, sub-function, NRC).
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SERVICE_NAMES: dict[int, str] = {
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2E: "WriteDataByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x3E: "TesterPresent",
}

_NRC_NAMES: dict[int, str] = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}

# Services where the response SID byte is followed by the same DID as the request
_DID_SERVICES = {0x22, 0x2E}

# Services where byte[1] is a sub-function (both request and response)
_SUB_FUNCTION_SERVICES = {0x10, 0x11, 0x19, 0x27, 0x28, 0x3E}

# RoutineControl: byte[1] = sub-function, bytes[2:4] = DID
_ROUTINE_CONTROL = 0x31


@dataclass
class DecodedUDS:
    service_id: int
    service_name: str
    is_response: bool
    did: int | None = None
    sub_function: int | None = None
    nrc: int | None = None
    nrc_name: str | None = None
    nrc_service_id: int | None = None


def decode(payload: bytes) -> DecodedUDS | None:
    """Decode a reassembled UDS payload into metadata.

    Returns None if the payload is not a recognized UDS frame.
    """
    if not payload:
        return None

    sid = payload[0]

    if sid == 0x7F:
        if len(payload) < 3:
            return None
        nrc_code = payload[2]
        return DecodedUDS(
            service_id=0x7F,
            service_name="NegativeResponse",
            is_response=True,
            nrc=nrc_code,
            nrc_name=_NRC_NAMES.get(nrc_code),
            nrc_service_id=payload[1],
        )

    is_response = sid >= 0x40
    req_sid = sid - 0x40 if is_response else sid

    if req_sid not in _SERVICE_NAMES:
        return None

    result = DecodedUDS(
        service_id=req_sid,
        service_name=_SERVICE_NAMES[req_sid],
        is_response=is_response,
    )

    if req_sid in _DID_SERVICES:
        if len(payload) >= 3:
            result.did = (payload[1] << 8) | payload[2]
    elif req_sid == _ROUTINE_CONTROL:
        if len(payload) >= 2:
            result.sub_function = payload[1]
        if len(payload) >= 4:
            result.did = (payload[2] << 8) | payload[3]
    elif req_sid in _SUB_FUNCTION_SERVICES:
        if len(payload) >= 2:
            result.sub_function = payload[1]

    return result


# ---------------------------------------------------------------------------
# Transaction data model
# ---------------------------------------------------------------------------


@dataclass
class UDSTransaction:
    """One complete UDS request–response pair (or a timed-out request).

    status values:
      "ok"      – positive response received
      "nrc"     – negative response received (see nrc / nrc_name)
      "timeout" – no response within the timeout window
    """

    timestamp: float
    request_id: int
    response_id: int
    service_id: int
    service_name: str
    req_frame_type: str       # "SF" | "MF"  (of the request)
    rsp_frame_type: str | None  # "SF" | "MF"  (of the response; None on timeout)
    status: str               # "ok" | "nrc" | "timeout"
    did: int | None = None
    sub_function: int | None = None
    req_length: int = 0
    rsp_length: int = 0
    nrc: int | None = None
    nrc_name: str | None = None
    duration_ms: float | None = None
    pending_count: int = 0        # number of NRC 0x78 responses before final answer
    req_payload: bytes | None = field(default=None, repr=False)
    rsp_payload: bytes | None = field(default=None, repr=False)
