"""Tests for the TransactionManager."""

import time
import pytest
from udsdump.transaction import TransactionManager


def _pad(data: bytes) -> bytes:
    return data + b"\xcc" * (8 - len(data))


ID_PAIRS = {0x680: 0x690}


class TestSuccessfulTransaction:
    def test_sf_read_data_by_identifier(self):
        mgr = TransactionManager(ID_PAIRS)
        t0 = 1000.0

        # Request: 0x22 DID=0x0100 (SF, 3 bytes)
        req_frame = _pad(b"\x03\x22\x01\x00")
        assert mgr.feed(0x680, req_frame, t0) is None

        # Response: 0x62 DID=0x0100 data=0xDEAD (SF, 5 bytes)
        rsp_frame = _pad(b"\x05\x62\x01\x00\xDE\xAD")
        tx = mgr.feed(0x690, rsp_frame, t0 + 0.008)

        assert tx is not None
        assert tx.status == "ok"
        assert tx.service_id == 0x22
        assert tx.service_name == "ReadDataByIdentifier"
        assert tx.did == 0x0100
        assert tx.req_frame_type == "SF"
        assert tx.rsp_frame_type == "SF"
        assert tx.request_id == 0x680
        assert tx.response_id == 0x690
        assert abs(tx.duration_ms - 8.0) < 0.1

    def test_diagnostic_session_control(self):
        mgr = TransactionManager(ID_PAIRS)
        t0 = 2000.0
        req = _pad(b"\x02\x10\x03")
        mgr.feed(0x680, req, t0)
        rsp = _pad(b"\x02\x50\x03")
        tx = mgr.feed(0x690, rsp, t0 + 0.005)
        assert tx is not None
        assert tx.status == "ok"
        assert tx.sub_function == 0x03
        assert tx.did is None

    def test_request_and_response_lengths(self):
        mgr = TransactionManager(ID_PAIRS)
        t0 = 3000.0
        req = _pad(b"\x05\x2E\x02\x3A\xDE\xAD")  # WriteDataByIdentifier, 5 bytes
        mgr.feed(0x680, req, t0)
        rsp = _pad(b"\x03\x6E\x02\x3A")           # positive response, 3 bytes
        tx = mgr.feed(0x690, rsp, t0 + 0.010)
        assert tx.req_length == 5
        assert tx.rsp_length == 3


class TestNegativeResponse:
    def test_nrc_transaction(self):
        mgr = TransactionManager(ID_PAIRS)
        t0 = 4000.0
        req = _pad(b"\x03\x22\x01\x00")
        mgr.feed(0x680, req, t0)
        nrc = _pad(b"\x03\x7F\x22\x22")
        tx = mgr.feed(0x690, nrc, t0 + 0.007)
        assert tx is not None
        assert tx.status == "nrc"
        assert tx.nrc == 0x22
        assert tx.nrc_name == "conditionsNotCorrect"
        assert tx.duration_ms is not None


class TestTimeout:
    def test_expired_request(self):
        mgr = TransactionManager(ID_PAIRS, timeout=1.0)
        t0 = 5000.0
        req = _pad(b"\x03\x22\x01\x00")
        mgr.feed(0x680, req, t0)

        # Before timeout: nothing
        assert mgr.check_timeouts(t0 + 0.5) == []

        # After timeout
        expired = mgr.check_timeouts(t0 + 1.5)
        assert len(expired) == 1
        tx = expired[0]
        assert tx.status == "timeout"
        assert tx.service_id == 0x22
        assert tx.duration_ms is None
        assert tx.rsp_length == 0

    def test_response_after_timeout_ignored(self):
        mgr = TransactionManager(ID_PAIRS, timeout=1.0)
        t0 = 6000.0
        req = _pad(b"\x03\x22\x01\x00")
        mgr.feed(0x680, req, t0)
        mgr.check_timeouts(t0 + 2.0)  # expire it

        rsp = _pad(b"\x05\x62\x01\x00\xDE\xAD")
        tx = mgr.feed(0x690, rsp, t0 + 2.5)
        assert tx is None


class TestParallelConversations:
    def test_two_id_pairs_independent(self):
        pairs = {0x680: 0x690, 0x6A1: 0x6B1}
        mgr = TransactionManager(pairs)
        t0 = 7000.0

        # Start two requests simultaneously
        req_a = _pad(b"\x03\x22\x01\x00")
        req_b = _pad(b"\x02\x10\x01")
        mgr.feed(0x680, req_a, t0)
        mgr.feed(0x6A1, req_b, t0 + 0.001)

        # Response for B arrives first
        rsp_b = _pad(b"\x02\x50\x01")
        tx_b = mgr.feed(0x6B1, rsp_b, t0 + 0.005)
        assert tx_b is not None
        assert tx_b.request_id == 0x6A1
        assert tx_b.service_id == 0x10

        # Response for A arrives later
        rsp_a = _pad(b"\x05\x62\x01\x00\xDE\xAD")
        tx_a = mgr.feed(0x690, rsp_a, t0 + 0.010)
        assert tx_a is not None
        assert tx_a.request_id == 0x680
        assert tx_a.service_id == 0x22


class TestPayload:
    def test_payload_included_when_requested(self):
        mgr = TransactionManager(ID_PAIRS, include_payload=True)
        t0 = 8000.0
        req = _pad(b"\x03\x22\x01\x00")
        mgr.feed(0x680, req, t0)
        rsp = _pad(b"\x05\x62\x01\x00\xDE\xAD")
        tx = mgr.feed(0x690, rsp, t0 + 0.008)
        assert tx.req_payload == b"\x22\x01\x00"
        assert tx.rsp_payload == b"\x62\x01\x00\xDE\xAD"

    def test_payload_excluded_by_default(self):
        mgr = TransactionManager(ID_PAIRS)
        t0 = 9000.0
        req = _pad(b"\x03\x22\x01\x00")
        mgr.feed(0x680, req, t0)
        rsp = _pad(b"\x05\x62\x01\x00\xDE\xAD")
        tx = mgr.feed(0x690, rsp, t0 + 0.008)
        assert tx.req_payload is None
        assert tx.rsp_payload is None


class TestMultiFrameTransaction:
    def test_mf_request_sf_response(self):
        mgr = TransactionManager(ID_PAIRS)
        t0 = 10000.0

        # MF request: 10-byte WriteDataByIdentifier
        payload = b"\x2E\x02\x3A" + b"\xAB" * 7  # 10 bytes
        ff = bytes([0x10, 0x0A]) + payload[:6]
        mgr.feed(0x680, ff, t0)
        cf = bytes([0x21]) + payload[6:] + b"\xcc" * 3
        assert mgr.feed(0x680, cf, t0 + 0.001) is None

        # SF response
        rsp = _pad(b"\x03\x6E\x02\x3A")
        tx = mgr.feed(0x690, rsp, t0 + 0.010)
        assert tx is not None
        assert tx.req_frame_type == "MF"
        assert tx.rsp_frame_type == "SF"
        assert tx.status == "ok"
        assert tx.req_length == 10

    def test_sf_request_mf_response(self):
        """ReadDataByIdentifier: SF request, large MF response – the common case
        where the old code incorrectly showed 'SF' for both sides."""
        mgr = TransactionManager(ID_PAIRS)
        t0 = 11000.0

        # SF request: ReadDataByIdentifier DID=0x0100
        req = _pad(b"\x03\x22\x01\x00")
        mgr.feed(0x680, req, t0)

        # MF response: 10-byte payload starting with 0x62 0x01 0x00
        rsp_payload = b"\x62\x01\x00" + b"\xAB" * 7  # 10 bytes
        ff = bytes([0x10, 0x0A]) + rsp_payload[:6]
        assert mgr.feed(0x690, ff, t0 + 0.005) is None
        cf = bytes([0x21]) + rsp_payload[6:] + b"\xcc" * 3
        tx = mgr.feed(0x690, cf, t0 + 0.006)

        assert tx is not None
        assert tx.req_frame_type == "SF"
        assert tx.rsp_frame_type == "MF"
        assert tx.status == "ok"
        assert tx.did == 0x0100
        assert tx.rsp_length == 10
