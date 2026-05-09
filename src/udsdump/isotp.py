"""ISO 15765-2 (ISO-TP) passive reassembler for udsdump.

Adapted from E3onCANserver (https://github.com/MyHomeMyData/E3onCANserver)
by the same author. This version is read-only – it observes traffic without
sending Flow Control frames.
"""

from __future__ import annotations

from typing import NamedTuple

_SF = 0x0
_FF = 0x1
_CF = 0x2
_FC = 0x3


class AssemblyResult(NamedTuple):
    payload: bytes
    frame_type: str  # "SF" or "MF"


class ISOTPAssembler:
    """Passive ISO-TP reassembler for one CAN ID (one direction).

    Call feed() for every CAN frame from this CAN ID.  Returns an
    AssemblyResult when a complete message is assembled, None otherwise.
    """

    def __init__(self) -> None:
        self._reset()

    def _reset(self) -> None:
        self._expected_length: int = 0
        self._buffer: bytearray = bytearray()
        self._next_seq: int = 1
        self._active: bool = False

    def feed(self, data: bytes) -> AssemblyResult | None:
        if not data:
            return None
        frame_type = (data[0] >> 4) & 0x0F
        if frame_type == _SF:
            return self._handle_sf(data)
        if frame_type == _FF:
            self._handle_ff(data)
            return None
        if frame_type == _CF:
            return self._handle_cf(data)
        # FC frames (0x3): observed but ignored – we don't send FC
        return None

    def _handle_sf(self, data: bytes) -> AssemblyResult | None:
        length = data[0] & 0x0F
        if length == 0 or length > 7:
            return None
        self._reset()
        return AssemblyResult(bytes(data[1 : 1 + length]), "SF")

    def _handle_ff(self, data: bytes) -> None:
        length = ((data[0] & 0x0F) << 8) | data[1]
        if length < 8:
            return
        self._reset()
        self._expected_length = length
        self._buffer.extend(data[2:8])
        self._next_seq = 1
        self._active = True

    def _handle_cf(self, data: bytes) -> AssemblyResult | None:
        if not self._active:
            return None
        seq = data[0] & 0x0F
        if seq != self._next_seq:
            self._reset()
            return None
        remaining = self._expected_length - len(self._buffer)
        self._buffer.extend(data[1 : 1 + min(7, remaining)])
        self._next_seq = (self._next_seq + 1) % 16
        if len(self._buffer) >= self._expected_length:
            payload = bytes(self._buffer[: self._expected_length])
            self._reset()
            return AssemblyResult(payload, "MF")
        return None

    @property
    def is_active(self) -> bool:
        """True while a multi-frame message is being assembled."""
        return self._active

    def abort(self) -> None:
        """Discard any partially assembled message."""
        self._reset()
