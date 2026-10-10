"""Tests for GD Arena personas definitions."""

import pytest
from backend.engine.personas import (
    MODERATOR,
    DOMINATOR,
    DATA_DRIVEN,
    BRIDGER,
    get_persona_by_id,
    get_active_panel,
)


def test_persona_attributes():
    """Verify all 4 personas have proper attributes and voice mappings."""
    assert MODERATOR.name == "Arjun"
    assert MODERATOR.avatar_id == "moderator"
    assert MODERATOR.voice_speaker == "arjun"

    assert DOMINATOR.name == "Priya"
    assert DOMINATOR.avatar_id == "dominator"
    assert DOMINATOR.voice_speaker == "shubh"

    assert DATA_DRIVEN.name == "Anushka"
    assert DATA_DRIVEN.avatar_id == "data_driven"
    assert DATA_DRIVEN.voice_speaker == "anushka"

    assert BRIDGER.name == "Meera"
    assert BRIDGER.avatar_id == "bridger"
    assert BRIDGER.voice_speaker == "meera"


def test_get_persona_by_id():
    """Verify lookup by ID works for all canonical IDs."""
    assert get_persona_by_id("moderator") == MODERATOR
    assert get_persona_by_id("dominator") == DOMINATOR
    assert get_persona_by_id("data_driven") == DATA_DRIVEN
    assert get_persona_by_id("data-driven") == DATA_DRIVEN
    assert get_persona_by_id("bridger") == BRIDGER
    assert get_persona_by_id("unknown_id") is None


def test_active_panel_selection():
    """Verify default panel selection matches GD requirements."""
    panel_3 = get_active_panel(3)
    assert len(panel_3) == 3
    assert MODERATOR in panel_3
    assert DOMINATOR in panel_3
    assert BRIDGER in panel_3

    panel_4 = get_active_panel(4)
    assert len(panel_4) == 4
    assert DATA_DRIVEN in panel_4
