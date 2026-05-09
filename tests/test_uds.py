"""Tests for the UDS decoder."""

import pytest
from udsdump.uds import decode


class TestRequests:
    def test_read_data_by_identifier(self):
        d = decode(b"\x22\x01\x00")
        assert d is not None
        assert d.service_id == 0x22
        assert d.service_name == "ReadDataByIdentifier"
        assert d.is_response is False
        assert d.did == 0x0100
        assert d.sub_function is None

    def test_write_data_by_identifier(self):
        d = decode(b"\x2E\x02\x3A\xDE\xAD")
        assert d.service_id == 0x2E
        assert d.did == 0x023A
        assert d.is_response is False

    def test_diagnostic_session_control(self):
        d = decode(b"\x10\x03")
        assert d.service_id == 0x10
        assert d.sub_function == 0x03
        assert d.did is None

    def test_routine_control(self):
        d = decode(b"\x31\x01\xFF\x00")
        assert d.service_id == 0x31
        assert d.sub_function == 0x01
        assert d.did == 0xFF00

    def test_tester_present(self):
        d = decode(b"\x3E\x00")
        assert d.service_id == 0x3E
        assert d.sub_function == 0x00

    def test_unknown_sid_returns_none(self):
        # 0x99 is not a known request SID
        assert decode(b"\x99\x01") is None

    def test_empty_returns_none(self):
        assert decode(b"") is None


class TestPositiveResponses:
    def test_read_data_response(self):
        d = decode(b"\x62\x01\x00\xDE\xAD\xBE\xEF")
        assert d.service_id == 0x22
        assert d.service_name == "ReadDataByIdentifier"
        assert d.is_response is True
        assert d.did == 0x0100

    def test_diagnostic_session_control_response(self):
        d = decode(b"\x50\x03")
        assert d.service_id == 0x10
        assert d.is_response is True
        assert d.sub_function == 0x03

    def test_tester_present_response(self):
        d = decode(b"\x7E\x00")
        assert d.service_id == 0x3E
        assert d.is_response is True
        assert d.sub_function == 0x00


class TestNegativeResponse:
    def test_nrc_conditions_not_correct(self):
        d = decode(b"\x7F\x22\x22")
        assert d.service_id == 0x7F
        assert d.service_name == "NegativeResponse"
        assert d.is_response is True
        assert d.nrc == 0x22
        assert d.nrc_name == "conditionsNotCorrect"
        assert d.nrc_service_id == 0x22

    def test_nrc_security_access_denied(self):
        d = decode(b"\x7F\x27\x33")
        assert d.nrc == 0x33
        assert d.nrc_name == "securityAccessDenied"

    def test_nrc_unknown_code(self):
        d = decode(b"\x7F\x22\xAB")
        assert d.nrc == 0xAB
        assert d.nrc_name is None

    def test_nrc_too_short(self):
        assert decode(b"\x7F\x22") is None
