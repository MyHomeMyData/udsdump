"""Tests for the ISO-TP passive assembler."""

import pytest
from udsdump.isotp import ISOTPAssembler


def _pad(data: bytes) -> bytes:
    return data + b"\xcc" * (8 - len(data))


class TestSingleFrame:
    def test_basic(self):
        asm = ISOTPAssembler()
        result = asm.feed(_pad(b"\x03\x22\x01\x00"))
        assert result is not None
        assert result.payload == b"\x22\x01\x00"
        assert result.frame_type == "SF"

    def test_max_sf_length(self):
        asm = ISOTPAssembler()
        payload = bytes(range(7))
        frame = bytes([0x07]) + payload
        result = asm.feed(frame)
        assert result is not None
        assert result.payload == payload

    def test_zero_length_ignored(self):
        asm = ISOTPAssembler()
        assert asm.feed(_pad(b"\x00\x22\x01\x00")) is None

    def test_length_over_7_ignored(self):
        asm = ISOTPAssembler()
        assert asm.feed(_pad(b"\x08\x22\x01\x00")) is None


class TestMultiFrame:
    def test_two_frame_message(self):
        asm = ISOTPAssembler()
        # FF: total length 10, first 6 bytes of payload
        payload_full = bytes(range(10))
        ff = bytes([0x10, 0x0A]) + payload_full[:6]
        assert asm.feed(ff) is None
        assert asm.is_active

        # CF seq=1: remaining 4 bytes
        cf = bytes([0x21]) + payload_full[6:] + b"\xcc" * 3
        result = asm.feed(cf)
        assert result is not None
        assert result.payload == payload_full
        assert result.frame_type == "MF"
        assert not asm.is_active

    def test_three_cf_frames(self):
        asm = ISOTPAssembler()
        payload_full = bytes(range(20))  # 6 in FF, 7 in CF1, 7 in CF2
        ff = bytes([0x10, 0x14]) + payload_full[:6]
        asm.feed(ff)

        cf1 = bytes([0x21]) + payload_full[6:13]
        assert asm.feed(cf1) is None

        cf2 = bytes([0x22]) + payload_full[13:20] + b"\xcc"
        result = asm.feed(cf2)
        assert result is not None
        assert result.payload == payload_full

    def test_sequence_error_resets(self):
        asm = ISOTPAssembler()
        ff = bytes([0x10, 0x0A]) + b"\x00" * 6
        asm.feed(ff)
        # Wrong sequence number (2 instead of 1)
        cf_bad = bytes([0x22]) + b"\x00" * 7
        assert asm.feed(cf_bad) is None
        assert not asm.is_active

    def test_fc_frame_ignored(self):
        asm = ISOTPAssembler()
        fc = b"\x30\x00\x00\xcc\xcc\xcc\xcc\xcc"
        assert asm.feed(fc) is None

    def test_cf_without_ff_ignored(self):
        asm = ISOTPAssembler()
        cf = bytes([0x21]) + b"\x00" * 7
        assert asm.feed(cf) is None

    def test_seq_wraps_at_15(self):
        asm = ISOTPAssembler()
        # Build a message needing 16 CFs (6 + 16*7 = 118 bytes total)
        total = 6 + 16 * 7  # 118
        payload_full = bytes(range(total % 256)) * 2
        payload_full = payload_full[:total]
        ff = bytes([0x10 | ((total >> 8) & 0x0F), total & 0xFF]) + payload_full[:6]
        asm.feed(ff)
        remaining = payload_full[6:]
        for i in range(16):
            seq = (i + 1) % 16
            chunk = remaining[i * 7 : (i + 1) * 7]
            cf = bytes([0x20 | seq]) + chunk
            result = asm.feed(cf)
            if i < 15:
                assert result is None
            else:
                assert result is not None
                assert result.payload == payload_full


class TestAbort:
    def test_abort_clears_state(self):
        asm = ISOTPAssembler()
        asm.feed(bytes([0x10, 0x0A]) + b"\x00" * 6)
        assert asm.is_active
        asm.abort()
        assert not asm.is_active
