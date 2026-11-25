"""Tests for security.py (section 12.4)."""

from __future__ import annotations

import re

from stand_allocation import config
from stand_allocation.security import etag_for, etag_matches, key_fingerprint, key_matches


def test_key_fingerprint_is_8_hex() -> None:
    fp = key_fingerprint("testkey01234567890123456789012345678901")
    assert len(fp) == config.FINGERPRINT_HEX_LENGTH
    assert re.fullmatch(r"[0-9a-f]{8}", fp)


def test_key_matches() -> None:
    keys = ["aaaabbbbccccddddeeeeffff00001111", "111122223333444455556666777788889999"]
    assert key_matches("aaaabbbbccccddddeeeeffff00001111", keys) is True
    assert key_matches("wrong", keys) is False
    assert key_matches(None, keys) is False


def test_etag() -> None:
    etag = etag_for("run-0001", "/allocations?limit=10")
    assert etag_matches(etag, etag) is True
    assert etag_matches("*", etag) is True
    assert etag_matches('"deadbeef"', etag) is False
    assert etag_matches(None, etag) is False
    assert etag_matches("W/\"" + etag.strip('"') + "\"", etag) is False


def test_request_id_pattern() -> None:
    pattern = re.compile(config.REQUEST_ID_PATTERN)
    assert pattern.fullmatch("aB3.x-9") is None  # too short
    assert pattern.fullmatch("aB3.x-9AbCdEfG") is not None
    assert pattern.fullmatch("bad!id") is None
