"""Tests for GDOrchestrator turn-taking state machine, floor handoff, and interruption handling."""

import asyncio
import base64
import pytest

from backend.config import settings
from backend.engine import gd_orchestrator
from backend.engine.gd_orchestrator import GDOrchestrator


def _chunk(seconds: float = 0.1) -> str:
    """Base64 PCM16 16 kHz mono of the given length."""
    return base64.b64encode(b"\x01\x00" * int(16000 * seconds)).decode("utf-8")


class Client:
    """Fake client: records messages and reports playback as finished, like the browser does."""

    def __init__(self):
        self.messages = []
        self.orchestrator = GDOrchestrator(send_callback=self.send)
        self.auto_ack = True

    async def send(self, msg: dict):
        self.messages.append(msg)
        if self.auto_ack and msg.get("type") == "agent_speaking":
            asyncio.get_running_loop().call_later(
                0.01, self.orchestrator.handle_playback_finished, msg["turn_id"]
            )

    def of_type(self, kind: str):
        return [m for m in self.messages if m.get("type") == kind]

    def texts(self, speaker: str = None):
        return [
            m["text"] for m in self.of_type("transcript_update")
            if speaker is None or m["speaker"] == speaker
        ]

    async def wait_for(self, predicate, timeout: float = 3.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError("condition not reached; messages: %s" % [
                    (m["type"], m.get("speaker"), m.get("text", m.get("floor")))
                    for m in self.messages if m["type"] != "timer_tick"
                ])
            await asyncio.sleep(0.01)


@pytest.fixture
def fast_floor(monkeypatch):
    monkeypatch.setattr(settings, "CANDIDATE_RESPONSE_TIMEOUT", 0.05)
    monkeypatch.setattr(settings, "CHECKIN_REPLY_TIMEOUT", 0.05)
    monkeypatch.setattr(settings, "USER_TURN_END_SILENCE", 0.05)


@pytest.mark.asyncio
async def test_orchestrator_start_session():
    """Verify start_session initializes session, emits opening prompt, and starts timer."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="AI in Job Markets", panel_size=3)

    assert orchestrator.is_active is True
    assert orchestrator.topic == "AI in Job Markets"
    assert len(orchestrator.panel) == 3

    await asyncio.sleep(0.1)

    types = [m["type"] for m in client.messages]
    assert "timer_tick" in types
    assert "transcript_update" in types
    assert "agent_speaking" in types

    # The opening invites a named panelist to start.
    opening = client.of_type("transcript_update")[0]
    assert opening["speaker"] == "Arjun"
    assert "start us off" in opening["text"]

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_panel_hands_floor_to_candidate_with_a_question():
    """After a few panel turns a panelist asks the candidate a question and the floor opens."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="AI in Job Markets", panel_size=3)

    await client.wait_for(lambda: orchestrator.floor == "user")

    question = [m for m in client.of_type("agent_speaking") if m["yields_floor"]]
    assert len(question) == 1
    assert "?" in question[0]["text"]
    floor_msg = client.of_type("turn_update")[-1]
    assert floor_msg == {"type": "turn_update", "floor": "user", "speaker": question[0]["speaker"]}

    # Clips carry turn ids that pair them with their transcript lines.
    turn_ids = [m["turn_id"] for m in client.of_type("agent_speaking")]
    assert turn_ids == sorted(turn_ids)
    assert {m["turn_id"] for m in client.of_type("transcript_update")} <= set(turn_ids)

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_audio_is_ignored_while_the_panel_holds_the_floor():
    """Candidate audio during panel speech (e.g. speaker echo) must not interrupt or buffer."""
    client = Client()
    client.auto_ack = False
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Startups vs Big Tech", panel_size=3)
    await asyncio.sleep(0.05)

    await orchestrator.handle_audio_chunk(_chunk())

    assert orchestrator.floor == "panel"
    assert len(orchestrator.user_audio_buffer) == 0
    assert client.of_type("agent_interrupted") == []

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_silence_after_question_triggers_check_in(fast_floor):
    """No reply within CANDIDATE_RESPONSE_TIMEOUT -> the asker checks in, then the floor reopens."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Corporate Governance", panel_size=3)
    await client.wait_for(lambda: orchestrator.floor == "user")
    asker = orchestrator.handoff.asker.name

    await client.wait_for(lambda: any("Can you hear me" in t for t in client.texts(asker)))
    await client.wait_for(lambda: orchestrator.floor == "user" and orchestrator.handoff.checked_in)

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_continued_silence_moves_the_discussion_on(fast_floor):
    """Silence after the check-in too -> the moderator moves on and the panel resumes."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Corporate Governance", panel_size=3)

    await client.wait_for(lambda: any("come back to you" in t for t in client.texts("Arjun")))
    assert orchestrator.handoff is None or not orchestrator.handoff.checked_in

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_repeat_request_replays_the_question(fast_floor, monkeypatch):
    async def fake_stt(audio_bytes, language_code="en-IN", **_):
        return "Sorry, could you repeat that?"

    monkeypatch.setattr(gd_orchestrator, "transcribe_audio_bytes", fake_stt)
    monkeypatch.setattr(settings, "CANDIDATE_RESPONSE_TIMEOUT", 5.0)

    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Remote Work", panel_size=3)
    await client.wait_for(lambda: orchestrator.floor == "user")
    question = orchestrator.handoff.question.text

    await orchestrator.handle_audio_chunk(_chunk())
    await client.wait_for(lambda: client.texts().count(question) == 2)

    assert "Sorry, could you repeat that?" in client.texts("User")
    assert any("let me repeat" in t for t in client.texts())
    await client.wait_for(lambda: orchestrator.floor == "user")

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_candidate_answer_gets_acknowledged_and_answered(fast_floor, monkeypatch):
    """A real answer: instant backchannel from the asker, then another panelist responds to it."""
    monkeypatch.setattr(settings, "CANDIDATE_RESPONSE_TIMEOUT", 5.0)

    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="AI in Job Markets", panel_size=3)
    await client.wait_for(lambda: orchestrator.floor == "user")
    asker = orchestrator.handoff.asker.name
    clips_before = len(client.of_type("agent_speaking"))

    for _ in range(15):  # 1.5 s of speech
        await orchestrator.handle_audio_chunk(_chunk())

    await client.wait_for(lambda: len(client.texts("User")) == 1)
    await client.wait_for(lambda: len(client.of_type("agent_speaking")) >= clips_before + 2)

    ack, reply = client.of_type("agent_speaking")[clips_before:clips_before + 2]
    assert ack["speaker"] == asker
    assert ack["text"] not in client.texts()  # backchannel, not a transcript line
    assert reply["speaker"] != asker
    assert reply["text"] in client.texts(reply["speaker"])

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_user_interruption():
    """Verify user_interrupted halts active AI speech and emits agent_interrupted message."""
    client = Client()
    client.auto_ack = False
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Electric Vehicles in India", panel_size=3)

    await asyncio.sleep(0.05)
    assert orchestrator.is_ai_speaking is True
    current_speaker = orchestrator.current_speaker

    await orchestrator.handle_user_interrupted()

    assert orchestrator.is_ai_speaking is False
    assert orchestrator.interruptions_handled == 1
    assert orchestrator.floor == "user"

    interrupted_msgs = client.of_type("agent_interrupted")
    assert len(interrupted_msgs) == 1
    assert interrupted_msgs[0]["speaker"] == current_speaker

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_end_session_produces_final_report():
    """Verify end_session generates final report adhering to SCHEMA.md."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Work From Home Culture", panel_size=3)
    await asyncio.sleep(0.05)

    await orchestrator.end_session()
    assert orchestrator.is_active is False

    final_reports = client.of_type("final_report")
    assert len(final_reports) == 1
    report = final_reports[0]
    assert "metrics" in report
    assert "feedback" in report
    assert "speaking_time_distribution" in report["metrics"]


@pytest.mark.asyncio
async def test_timer_expiry_closes_and_sends_report(monkeypatch):
    """When time runs out the moderator closes and the final report is still delivered."""
    monkeypatch.setattr(gd_orchestrator, "DEFAULT_SESSION_SECONDS", 1)

    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Work From Home Culture", panel_size=3)

    await client.wait_for(lambda: client.of_type("final_report"), timeout=5.0)
    assert any("out of time" in t for t in client.texts("Arjun"))
    assert orchestrator.is_active is False


@pytest.mark.asyncio
async def test_orchestrator_panel_size_5():
    """Verify panel_size=5 activates all 5 panelists."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Future of AI in India", panel_size=5)

    assert len(orchestrator.panel) == 5
    names = [p.name for p in orchestrator.panel]
    assert names == ["Arjun", "Kabir", "Anushka", "Priya", "Rohan"]

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_orchestrator_indic_language_flow():
    """Verify start_session with Indic language (hi-IN) sets language and Hindi opening."""
    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(topic="Artificial Intelligence", panel_size=3, language="hi-IN")

    assert orchestrator.language == "hi-IN"
    await asyncio.sleep(0.05)

    hindi_opening = [t for t in client.texts("Arjun") if "swagat hai" in t]
    assert len(hindi_opening) == 1

    await orchestrator.end_session()


@pytest.mark.asyncio
async def test_candidate_can_stop_for_today_and_gets_a_summary(fast_floor, monkeypatch):
    """'Thank you, I'd like to continue another day' -> moderator summarizes, then the report."""
    async def fake_stt(audio_bytes, language_code="en-IN", **_):
        return "Thank you, I would like to continue it on another day."

    monkeypatch.setattr(gd_orchestrator, "transcribe_audio_bytes", fake_stt)
    monkeypatch.setattr(settings, "CANDIDATE_RESPONSE_TIMEOUT", 5.0)

    client = Client()
    orchestrator = client.orchestrator
    await orchestrator.start_session(
        topic="AI in Job Markets",
        panel_size=3,
        profile={"field": "Data science", "interests": "MLOps, recommender systems"},
    )
    assert orchestrator.candidate_profile == "works in Data science; knows about MLOps, recommender systems"
    await client.wait_for(lambda: orchestrator.floor == "user")

    await orchestrator.handle_audio_chunk(_chunk())
    await client.wait_for(lambda: client.of_type("final_report"))

    assert any("continue another day" in t for t in client.texts("Arjun"))
    assert orchestrator.is_active is False


def test_profile_reaches_the_question_prompt():
    from backend.engine.personas import DOMINATOR

    messages = DOMINATOR.format_chat_messages(
        topic="AI", recent_transcripts=[], mode="invite",
        candidate_profile="works in Cloud; knows about Kubernetes",
    )
    assert "works in Cloud; knows about Kubernetes" in messages[-1]["content"]
