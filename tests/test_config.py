"""Tests for config.py (section 12.4)."""

from __future__ import annotations

import importlib

import pytest

import stand_allocation.config as config


def _reload_with(**env) -> None:
    import os

    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    importlib.reload(config)


def test_placeholder_key_refused() -> None:
    with pytest.raises(SystemExit):
        _reload_with(API_KEYS="changeme")


def test_duplicate_key_refused() -> None:
    key = "testkey01234567890123456789012345678901"
    with pytest.raises(SystemExit):
        _reload_with(API_KEYS=f"{key},{key}")


def test_allowed_origins_parsed() -> None:
    key = "testkey01234567890123456789012345678901"
    try:
        _reload_with(
            API_KEYS=key,
            ALLOWED_ORIGINS="https://app.example.com, https://admin.example.com",
        )
        assert config.ALLOWED_ORIGINS == [
            "https://app.example.com",
            "https://admin.example.com",
        ]
    finally:
        _reload_with(API_KEYS=key, ALLOWED_ORIGINS=None)
