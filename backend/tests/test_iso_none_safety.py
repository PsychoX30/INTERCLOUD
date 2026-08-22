"""Test _iso helper handles None values from CRM nullable date fields."""
import pytest
from portal.routes.shared import _iso


def test_iso_handles_none():
    """_iso should return empty string when given None, not crash."""
    # This reproduces the production crash: CRM docs with assigned_at=None
    result = _iso(None)
    assert result == ""


def test_iso_handles_empty_string():
    """_iso should pass through empty strings unchanged."""
    assert _iso("") == ""


def test_iso_handles_iso_string():
    """_iso should pass through ISO strings unchanged."""
    iso_str = "2026-08-22T10:30:00Z"
    assert _iso(iso_str) == iso_str


def test_iso_handles_datetime():
    """_iso should format datetime objects."""
    from datetime import datetime, timezone
    dt = datetime(2026, 8, 22, 10, 30, 0, tzinfo=timezone.utc)
    result = _iso(dt)
    assert result.startswith("2026-08-22T10:30:00")
