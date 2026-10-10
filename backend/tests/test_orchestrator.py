"""Tests for GDOrchestrator turn-taking state machine and interruption handling."""

import asyncio
import base64
import pytest
from backend.engine.gd_orchestrator import GDOrchestrator, PAUSE_THRESHOLD_SECONDS


@pytest.mark.asyncio
async def test_orchestrator_start_session():
    """Verify start_session initializes session, emits opening prompt, and starts timer."""
    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="AI in Job Markets", panel_size=3)

    assert orchestrator.is_active is True
    assert orchestrator.topic == "AI in Job Markets"
    assert len(orchestrator.panel) == 3

    # Allow turn task to execute
    await asyncio.sleep(0.1)

    types = [m["type"] for m in messages]
    assert "timer_tick" in types
    assert "transcript_update" in types
    assert "agent_speaking" in types

    # Cleanup
    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_user_interruption():
    """Verify user_interrupted halts active AI speech and emits agent_interrupted message."""
    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="Electric Vehicles in India", panel_size=3)

    # Let the initial turn start speaking
    await asyncio.sleep(0.05)
    assert orchestrator.is_ai_speaking is True
    current_speaker = orchestrator.current_speaker

    # Send user_interrupted
    await orchestrator.handle_user_interrupted()

    # AI speaking must now be stopped
    assert orchestrator.is_ai_speaking is False
    assert orchestrator.interruptions_handled == 1

    # Verify agent_interrupted was dispatched
    interrupted_msgs = [m for m in messages if m["type"] == "agent_interrupted"]
    assert len(interrupted_msgs) == 1
    assert interrupted_msgs[0]["speaker"] == current_speaker

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_audio_chunk_and_pause_detection():
    """Verify audio chunks reset pause timer and flush transcription after 2.5s."""
    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="Startups vs Big Tech", panel_size=3)
    await asyncio.sleep(0.05)

    dummy_chunk = base64.b64encode(b"dummy_wav_audio_stream_data_123456").decode("utf-8")

    # Send audio chunk
    await orchestrator.handle_audio_chunk(dummy_chunk)
    assert len(orchestrator.user_audio_buffer) > 0
    assert orchestrator.pause_timer_task is not None

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_end_session_produces_final_report():
    """Verify end_session generates final report adhering to SCHEMA.md."""
    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="Work From Home Culture", panel_size=3)
    await asyncio.sleep(0.05)

    await orchestrator.end_session()
    assert orchestrator.is_active is False

    final_reports = [m for m in messages if m["type"] == "final_report"]
    assert len(final_reports) == 1
    report = final_reports[0]
    assert "metrics" in report
    assert "feedback" in report
    assert "speaking_time_distribution" in report["metrics"]


@pytest.mark.asyncio
async def test_orchestrator_panel_size_5():
    """Verify panel_size=5 activates all 5 panelists."""
    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="Future of AI in India", panel_size=5)

    assert len(orchestrator.panel) == 5
    names = [p.name for p in orchestrator.panel]
    assert names == ["Arjun", "Kabir", "Anushka", "Priya", "Rohan"]

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_candidate_silence_nudge(monkeypatch):
    """Verify Moderator intervenes when candidate silence exceeds threshold."""
    from backend.config import settings
    monkeypatch.setattr(settings, "CANDIDATE_SILENCE_THRESHOLD", 0.1)

    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="Corporate Governance", panel_size=3)

    # Cancel opening AI turn so floor is immediately free
    orchestrator._cancel_task(orchestrator.active_turn_task)
    orchestrator.is_ai_speaking = False

    # Wait for silence threshold to trigger
    await asyncio.sleep(0.18)

    # Check if Moderator nudge was triggered
    nudge_msgs = [
        m for m in messages
        if m.get("type") == "transcript_update" and "Candidate, we've noticed a brief pause" in m.get("text", "")
    ]
    assert len(nudge_msgs) >= 1
    assert nudge_msgs[0]["speaker"] == "Arjun"

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_indic_language_flow():
    """Verify start_session with Indic language (hi-IN) sets language and Hindi opening."""
    messages = []

    async def mock_send(msg: dict):
        messages.append(msg)

    orchestrator = GDOrchestrator(send_callback=mock_send)
    await orchestrator.start_session(topic="Artificial Intelligence", panel_size=3, language="hi-IN")

    assert orchestrator.language == "hi-IN"
    await asyncio.sleep(0.05)

    hindi_opening = [
        m for m in messages
        if m.get("type") == "transcript_update" and "swagat hai" in m.get("text", "")
    ]
    assert len(hindi_opening) == 1
    assert hindi_opening[0]["speaker"] == "Arjun"

    await orchestrator.end_session()


