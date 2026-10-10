"""Tests for GD Arena 5-panelist persona definitions."""

import pytest
from backend.engine.personas import (
    MODERATOR,
    DOMINATOR,
    DATA_DRIVEN,
    BRIDGER,
    QUIET_ANALYST,
    get_persona_by_id,
    get_active_panel,
)


def test_persona_attributes_5_panelists():
    """Verify all 5 personas have accurate attributes and Sarvam voice mappings."""
    # 1. Moderator
    assert MODERATOR.name == "Arjun"
    assert MODERATOR.avatar_id == "moderator"
    assert MODERATOR.voice_speaker == "arjun"

    # 2. Dominator
    assert DOMINATOR.name == "Kabir"
    assert DOMINATOR.avatar_id == "dominator"
    assert DOMINATOR.voice_speaker == "shubh"

    # 3. Data-Driven
    assert DATA_DRIVEN.name == "Anushka"
    assert DATA_DRIVEN.avatar_id == "data_driven"
    assert DATA_DRIVEN.voice_speaker == "anushka"

    # 4. Bridger
    assert BRIDGER.name == "Priya"
    assert BRIDGER.avatar_id == "bridger"
    assert BRIDGER.voice_speaker == "meera"

    # 5. Quiet Analyst
    assert QUIET_ANALYST.name == "Rohan"
    assert QUIET_ANALYST.avatar_id == "quiet_analyst"
    assert QUIET_ANALYST.voice_speaker == "arvind"


def test_get_persona_by_id():
    """Verify lookup by canonical avatar IDs."""
    assert get_persona_by_id("moderator") == MODERATOR
    assert get_persona_by_id("dominator") == DOMINATOR
    assert get_persona_by_id("data_driven") == DATA_DRIVEN
    assert get_persona_by_id("data-driven") == DATA_DRIVEN
    assert get_persona_by_id("bridger") == BRIDGER
    assert get_persona_by_id("quiet_analyst") == QUIET_ANALYST
    assert get_persona_by_id("quiet-analyst") == QUIET_ANALYST
    assert get_persona_by_id("unknown") is None


def test_active_panel_selection_n_panelists():
    """Verify panelist activation when panel size is N (3 to 5)."""
    panel_3 = get_active_panel(3)
    assert len(panel_3) == 3
    assert [p.avatar_id for p in panel_3] == ["moderator", "dominator", "data_driven"]

    panel_4 = get_active_panel(4)
    assert len(panel_4) == 4
    assert [p.avatar_id for p in panel_4] == ["moderator", "dominator", "data_driven", "bridger"]

    panel_5 = get_active_panel(5)
    assert len(panel_5) == 5
    assert [p.avatar_id for p in panel_5] == ["moderator", "dominator", "data_driven", "bridger", "quiet_analyst"]


def test_persona_language_prompt_formatting():
    """Verify chat messages incorporate target Indic language instructions."""
    messages_hi = MODERATOR.format_chat_messages(
        topic="Fintech Disruption",
        recent_transcripts=[{"speaker": "User", "text": "UPI growth has been exponential."}],
        language="hi-IN",
    )
    system_msg = next(m["content"] for m in messages_hi if m["role"] == "system")
    assert "Hindi or professional corporate Hinglish" in system_msg

    messages_ta = DOMINATOR.format_chat_messages(
        topic="Fintech Disruption",
        recent_transcripts=[],
        language="ta-IN",
    )
    system_msg_ta = next(m["content"] for m in messages_ta if m["role"] == "system")
    assert "Tamil or professional Tanglish" in system_msg_ta



def test_every_prompt_pins_the_topic():
    """Bots are told, in every mode, to stay strictly relevant to the topic."""
    for mode in ("discuss", "invite", "react", "custom"):
        messages = DATA_DRIVEN.format_chat_messages(
            topic="Mirrors", recent_transcripts=[], mode=mode, instruction="Say something."
        )
        system_msg = messages[0]["content"]
        assert 'topic is "Mirrors"' in system_msg
        assert "directly relevant" in system_msg
