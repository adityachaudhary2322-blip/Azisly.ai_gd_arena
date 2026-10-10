"""Pytest configuration and global fixtures for GD Arena backend tests."""

import pytest
from backend.config import settings


@pytest.fixture(autouse=True)
def default_mock_mode_for_tests(monkeypatch):
    """Ensure all tests run with MOCK_VOICE=True by default to conserve live credits."""
    monkeypatch.setattr(settings, "MOCK_VOICE", True)
