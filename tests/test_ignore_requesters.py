"""Tests for --ignore-requesters: _build_id_pairs filtering and CLI parsing."""

import pytest
from udsdump.monitor import _build_id_pairs
from udsdump.cli import _parse_ignore_requesters


class TestBuildIdPairsIgnore:
    def test_ignore_removes_req_id_from_offset_mode(self):
        pairs = _build_id_pairs((0x680, 0x682), 0x10, None, {0x681})
        assert 0x680 in pairs
        assert 0x681 not in pairs
        assert 0x682 in pairs

    def test_ignore_removes_req_id_from_explicit_pairs(self):
        explicit = [(0x680, 0x690), (0x691, 0x681), (0x696, 0x686)]
        pairs = _build_id_pairs((0x600, 0x6FF), 0x10, explicit, {0x691, 0x696})
        assert 0x680 in pairs
        assert 0x691 not in pairs
        assert 0x696 not in pairs

    def test_empty_ignore_set_is_noop(self):
        pairs = _build_id_pairs((0x680, 0x681), 0x10, None, set())
        assert len(pairs) == 2

    def test_none_ignore_is_noop(self):
        pairs = _build_id_pairs((0x680, 0x681), 0x10, None, None)
        assert len(pairs) == 2

    def test_ignore_all_leaves_empty(self):
        pairs = _build_id_pairs((0x680, 0x680), 0x10, None, {0x680})
        assert pairs == {}


class TestParseIgnoreRequesters:
    def test_single_with_prefix(self):
        assert _parse_ignore_requesters("0x691") == {0x691}

    def test_multiple_with_prefix(self):
        assert _parse_ignore_requesters("0x691,0x696") == {0x691, 0x696}

    def test_without_prefix(self):
        assert _parse_ignore_requesters("691,696") == {0x691, 0x696}

    def test_mixed_prefix(self):
        assert _parse_ignore_requesters("0x691,696") == {0x691, 0x696}

    def test_whitespace_around_values(self):
        assert _parse_ignore_requesters("0x691, 0x696") == {0x691, 0x696}

    def test_none_returns_empty_set(self):
        assert _parse_ignore_requesters(None) == set()

    def test_empty_string_returns_empty_set(self):
        assert _parse_ignore_requesters("") == set()

    def test_invalid_value_exits(self):
        with pytest.raises(SystemExit):
            _parse_ignore_requesters("xyz")
