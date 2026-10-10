"""Turn-taking state machine and multi-agent conversation orchestrator for GD Arena.

100% Sarvam AI powered (Saaras STT, Sarvam LLM, Bulbul TTS):
- The panel holds the floor and talks among itself. Every few turns a panelist
  ends their turn with a direct question to the candidate and hands them the floor.
- The candidate speaks only when handed the floor; their audio is ignored otherwise,
  so speaker echo can never cut a panelist off.
- If the candidate says nothing for CANDIDATE_RESPONSE_TIMEOUT seconds after the
  question finishes playing, the asker checks in ("Can you hear me? Should I repeat
  the question?"). Repeat requests replay the question; continued silence moves on.
- Smoothness: the next panelist's line and audio are prepared while the current clip
  plays, the asker acknowledges a long answer instantly while it is transcribed, and
  clip timing follows the client's `playback_finished` reports (with a fallback
  estimate if the client never reports).
- Multi-language Indic support: en-IN, hi-IN, ta-IN, te-IN, bn-IN, kn-IN.
- Activates first N personas (3 to 5) based on panel size.
"""

import asyncio
import base64
import dataclasses
import io
import logging
import random
import re
import time
import wave
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Deque, Dict, List, Optional

from backend.config import settings, SUPPORTED_LANGUAGES
from backend.engine.evaluator import evaluate_session
from backend.engine.personas import Persona, get_active_panel
from backend.services.sarvam_llm import (
    MOCK_DEFAULT_REPLY,
    MOCK_SUMMARY_EN,
    MOCK_SUMMARY_HI,
    get_sarvam_completion,
)
from backend.services.sarvam_stt import transcribe_audio_bytes
from backend.services.sarvam_tts import MOCK_AUDIO_PAYLOAD, synthesize_speech

logger = logging.getLogger(__name__)

SendCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]

# Kept for backwards compatibility; the live value is settings.USER_TURN_END_SILENCE.
PAUSE_THRESHOLD_SECONDS = 0.8
DEFAULT_SESSION_SECONDS = 420

# Client inserts roughly this much silence between different speakers.
SPEAKER_GAP_SECONDS = 0.35
# How long past a clip's estimated end we wait for `playback_finished` before assuming it
# (at least this, or the clip's own length again). The client always reports, so this only
# matters if it never does; erring long keeps the floor from opening mid-question.
PLAYBACK_SLACK_SECONDS = 6.0
# Candidate audio shorter than this is treated as a short reply ("repeat?", "yes"),
# not an answer worth an instant acknowledgement.
ACK_MIN_ANSWER_SECONDS = 1.2
PCM_BYTES_PER_SECOND = 16000 * 2

REPEAT_REQUEST = re.compile(
    r"\b(repeat|again|pardon|come again|say that|didn'?t (hear|get|catch)|can'?t hear|dobara|phir se)\b",
    re.IGNORECASE,
)
END_REQUEST = re.compile(
    r"(continue (it |this )?(on )?(another|some other|other|a different|next) (day|time)"
    r"|(want|like) to (stop|end|leave|finish)|let'?s (stop|end|wrap)|wrap (it |this )?up"
    r"|end (the|this) (session|discussion|gd)|stop (here|now|for today)|that'?s all for today"
    r"|band kar|khatam kar|kal continue)",
    re.IGNORECASE,
)
HEARING_CONFIRMATION = re.compile(
    r"\b(yes|yeah|yep|haan|i can hear|can hear you|audible|loud and clear)\b",
    re.IGNORECASE,
)

PHRASES: Dict[str, Dict[str, Any]] = {
    "en": {
        "opening": (
            "Welcome to this group discussion on '{topic}'. Let us establish a balanced framework "
            "examining both technological potential and socioeconomic impact. {name}, would you like to start us off?"
        ),
        "check_in": "Can you hear me? Should I repeat the question?",
        "repeat_intro": "Sure, let me repeat that.",
        "go_ahead": "Great, go ahead.",
        "not_caught": "Sorry, I didn't quite catch that. Could you say it again?",
        "move_on": "No worries, we'll come back to you. Let's keep going.",
        "time_up": "Sorry to cut in, but we're out of time for today.",
        "fallback_question": "What do you think?",
        "acks": ["Mm, okay.", "Right.", "I see.", "Okay, interesting."],
    },
    "hi": {
        "opening": (
            "Aap sabhi ka is group discussion mein swagat hai. Topic hai '{topic}'. "
            "Aaiye hum technological potential aur socioeconomic impact dono pehluon par charcha shuru karein. "
            "{name}, kya aap shuruaat karenge?"
        ),
        "check_in": "Kya aap mujhe sun pa rahe hain? Kya main sawaal dobara poochhun?",
        "repeat_intro": "Zaroor, sawaal phir se.",
        "go_ahead": "Accha, boliye.",
        "not_caught": "Maaf kijiye, theek se sunayi nahi diya. Kya aap dobara bolenge?",
        "move_on": "Koi baat nahi, hum aapke paas wapas aayenge. Chaliye aage badhte hain.",
        "time_up": "Maaf kijiye, beech mein tok raha hoon, aaj ka samay khatam ho gaya hai.",
        "fallback_question": "Aapka kya kehna hai?",
        "acks": ["Hmm, accha.", "Theek hai.", "Achha."],
    },
}


# Instructions for lines generated from the topic and conversation so far. The fixed
# PHRASES above are only fallbacks (mock mode, or when the LLM call fails).
INSTRUCTIONS = {
    "opening": (
        "Open this group discussion as the moderator: welcome everyone, frame the topic in one or two "
        "sentences with an angle specific to it, then invite {name} by name to start. Under 50 words."
    ),
    "check_in": (
        "You just asked the candidate a question and they have been silent for a moment. Briefly and "
        "naturally ask whether they can hear you, and offer to repeat the question. One short sentence."
    ),
    "move_on": (
        "The candidate has not responded. Briefly say you'll come back to them, then steer the discussion "
        "to a fresh angle of the topic. Under 35 words."
    ),
    "rephrase": (
        "The candidate asked you to repeat your question: '{question}'. Say 'Sure' and ask it again "
        "in simpler words. Under 30 words, ending with a question mark."
    ),
    "time_up": (
        "Politely cut in to say that today's time for this discussion is up. One short sentence; "
        "do not summarize yet."
    ),
    "summary": (
        "Summarize today's discussion in 2 to 3 spoken sentences: the main viewpoints raised, what the "
        "candidate contributed (refer to their actual points), and thank everyone{tail}. Under 70 words."
    ),
}


@dataclass
class Clip:
    """One synthesized panelist utterance, ready to send."""

    speaker: str
    avatar_id: str
    text: str
    audio_base64: str
    duration: float
    yields_floor: bool = False
    record: bool = True  # False for backchannels like "Mm, okay." (not added to the transcript)
    turn_id: int = 0


@dataclass
class _Outstanding:
    turn_id: int
    expected_end: float
    duration: float


@dataclass
class Handoff:
    """The question that handed the candidate the floor, plus prefetched follow-ups."""

    asker: Persona
    question: Clip
    check_in: Optional["asyncio.Task[Clip]"] = None
    ack: Optional["asyncio.Task[Clip]"] = None
    checked_in: bool = False


class GDOrchestrator:
    """State machine governing multi-agent Group Discussion session dynamics."""

    def __init__(self, send_callback: SendCallback):
        self.send_callback = send_callback

        # Session configuration
        self.topic: str = "Campus Recruitment Discussion"
        self.panel_size: int = 3
        self.language: str = "en-IN"
        self.panel: List[Persona] = []
        self.candidate_profile: str = ""
        self.session_seconds: int = DEFAULT_SESSION_SECONDS
        self.time_up_task: Optional[asyncio.Task] = None
        self.start_time: float = 0.0
        self.seconds_left: int = DEFAULT_SESSION_SECONDS
        self.is_active: bool = False

        # Conversational state
        self.transcript: List[Dict[str, Any]] = []
        self.floor: str = "panel"  # "panel" | "user"
        self.current_speaker: Optional[str] = None
        self.current_avatar_id: Optional[str] = None
        self.is_ai_speaking: bool = False
        self.last_ai_speaker: Optional[str] = None
        self.interruptions_handled: int = 0
        self.handoff: Optional[Handoff] = None
        self.turns_since_user: int = 0
        self.next_handoff_after: int = 3
        self.turn_counter: int = 0

        # Candidate silence tracking
        self.last_candidate_speech_time: float = 0.0
        self.user_spoke = asyncio.Event()

        # Audio buffering (16-bit PCM 16kHz mono chunks)
        self.user_audio_buffer = bytearray()

        # Client playback tracking
        self.outstanding: Deque[_Outstanding] = deque()
        self.playback_event = asyncio.Event()

        # Asynchronous tasks
        self.active_turn_task: Optional[asyncio.Task] = None  # panel speaking loop
        self.pause_timer_task: Optional[asyncio.Task] = None  # candidate end-of-turn detector
        self.user_turn_task: Optional[asyncio.Task] = None  # candidate response timeout
        self.timer_heartbeat_task: Optional[asyncio.Task] = None

    @property
    def _phrases(self) -> Dict[str, Any]:
        return PHRASES["hi" if self.language == "hi-IN" else "en"]

    # -----------------------------------------------------------------------
    # Message Dispatcher
    # -----------------------------------------------------------------------

    async def handle_client_message(self, message: Dict[str, Any]) -> None:
        """Route client WebSocket messages adhering to SCHEMA.md."""
        msg_type = message.get("type")

        if msg_type == "start_session":
            await self.start_session(
                topic=message.get("topic", "AI in Job Markets"),
                panel_size=int(message.get("panel_size", 3)),
                language=message.get("language", "en-IN"),
                profile=message.get("profile"),
                duration_seconds=message.get("duration_seconds"),
            )
        elif msg_type == "audio_chunk":
            await self.handle_audio_chunk(message.get("data", ""))
        elif msg_type == "playback_finished":
            self.handle_playback_finished(message.get("turn_id"))
        elif msg_type == "user_interrupted":
            await self.handle_user_interrupted()
        elif msg_type == "end_session":
            await self.end_session()
        else:
            logger.warning("Unknown client message received: %s", msg_type)

    # -----------------------------------------------------------------------
    # Session Lifecycle
    # -----------------------------------------------------------------------

    async def start_session(
        self,
        topic: str = "AI in Job Markets",
        panel_size: int = 3,
        language: str = "en-IN",
        profile: Optional[Dict[str, Any]] = None,
        duration_seconds: Optional[int] = None,
    ) -> None:
        """Initialize session and activate the first N panel personas with target language."""
        self.topic = topic
        self.candidate_profile = _describe_profile(profile)
        self.panel_size = max(3, min(5, panel_size))

        target_lang = language.strip()
        if target_lang in SUPPORTED_LANGUAGES:
            self.language = target_lang
        else:
            logger.warning("Language '%s' not in supported set; defaulting to 'en-IN'", language)
            self.language = "en-IN"

        self.panel = get_active_panel(self.panel_size)
        self.start_time = time.time()
        try:
            self.session_seconds = max(60, min(3600, int(duration_seconds)))
        except (TypeError, ValueError):
            self.session_seconds = DEFAULT_SESSION_SECONDS
        self.seconds_left = self.session_seconds
        self.is_active = True
        self.transcript.clear()
        self.interruptions_handled = 0
        self.user_audio_buffer.clear()
        self.outstanding.clear()
        self.last_ai_speaker = None
        self.handoff = None
        self.floor = "panel"
        self.turn_counter = 0
        self.turns_since_user = 0
        # Opening, one panelist, then the next panelist asks the candidate.
        self.next_handoff_after = 2
        self.last_candidate_speech_time = time.time()

        logger.info(
            "Session initiated: topic='%s', panel_size=%d (%s), language=%s",
            self.topic,
            len(self.panel),
            [p.name for p in self.panel],
            self.language,
        )

        self._cancel_task(self.timer_heartbeat_task)
        self.timer_heartbeat_task = asyncio.create_task(self._run_timer_heartbeat())

        moderator = self.panel[0]
        first_speaker = self._select_next_speaker(exclude=moderator.name)
        opening = asyncio.create_task(self._custom_clip(
            moderator,
            INSTRUCTIONS["opening"].format(name=first_speaker.name),
            self._phrases["opening"].format(topic=self.topic, name=first_speaker.name),
        ))
        # Ready in advance so the moderator can cut in the instant time runs out.
        self._cancel_task(self.time_up_task)
        self.time_up_task = asyncio.create_task(
            self._custom_clip(moderator, INSTRUCTIONS["time_up"], self._phrases["time_up"])
        )

        self.is_ai_speaking = True
        self.active_turn_task = asyncio.create_task(
            self._panel_loop(lead=opening, next_persona=first_speaker)
        )

    async def end_session(self) -> None:
        """Conclude session, compute metrics, and dispatch final_report."""
        if not self.is_active:
            return

        self.is_active = False
        self.is_ai_speaking = False
        self._cancel_task(self.timer_heartbeat_task)
        self._cancel_task(self.pause_timer_task)
        self._cancel_task(self.user_turn_task)
        self._cancel_task(self.active_turn_task)
        self._cancel_task(self.time_up_task)
        self._cancel_handoff_prefetch()

        # Keep whatever the candidate said right before ending.
        await self._transcribe_and_record_buffer()

        report = await evaluate_session(
            transcripts=self.transcript,
            interruptions_count=self.interruptions_handled,
        )

        await self._send(report)
        logger.info("Session ended. Dispatched final_report matching SCHEMA.md.")

    async def _close_discussion(self) -> None:
        """Time is up: the moderator cuts in (even mid-answer), summarizes, then the report is sent."""
        self._cancel_task(self.pause_timer_task)
        self._cancel_task(self.user_turn_task)
        self._cancel_task(self.active_turn_task)
        self._cancel_handoff_prefetch()
        self.handoff = None

        if self.floor == "user":
            await self._set_floor("panel")  # closes the candidate's mic
        elif self.outstanding:
            # A panelist is mid-line: stop them so the moderator can cut in now.
            await self._send({"type": "agent_interrupted", "speaker": self.current_speaker})
            self.outstanding.clear()
        self.is_ai_speaking = True

        try:
            time_up = await self.time_up_task if self.time_up_task else None
        except Exception:
            time_up = None
        try:
            if time_up is None:
                time_up = await self._make_clip(self.panel[0], self._phrases["time_up"])
            await self._dispatch(time_up)
            # Whatever the candidate was saying belongs in the summary and the report.
            await self._transcribe_and_record_buffer()
            await self._dispatch(await self._summary_clip(stopping_early=False))
            await self._wait_for_outstanding(0)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Closing remarks failed: %s", exc)
        await self.end_session()

    async def _summary_clip(self, stopping_early: bool) -> Clip:
        tail = ", saying you'll continue another day" if stopping_early else ""
        fallback = MOCK_SUMMARY_HI if self.language == "hi-IN" else MOCK_SUMMARY_EN
        return await self._custom_clip(
            self.panel[0],
            INSTRUCTIONS["summary"].format(tail=tail),
            fallback,
            history=24,
            max_tokens=200,
        )

    @staticmethod
    def _llm_enabled() -> bool:
        return not settings.MOCK_VOICE and bool(settings.SARVAM_API_KEY.strip())

    async def _custom_clip(
        self,
        persona: Persona,
        instruction: str,
        fallback: str,
        yields_floor: bool = False,
        history: int = 10,
        max_tokens: int = 110,
    ) -> Clip:
        """A line written for this topic and conversation, falling back to a fixed phrase."""
        text = fallback
        if self._llm_enabled():
            messages = persona.format_chat_messages(
                topic=self.topic,
                recent_transcripts=self.transcript[-history:],
                language=self.language,
                mode="custom",
                candidate_profile=self.candidate_profile,
                instruction=instruction,
            )
            try:
                raw = await get_sarvam_completion(messages=messages, temperature=0.7, max_tokens=max_tokens)
                text = self._clean_line(raw, persona) or fallback
            except Exception as exc:
                logger.warning("Custom line failed for %s: %s", persona.name, exc)
        if yields_floor and "?" not in text:
            text = f"{text} {self._phrases['fallback_question']}"
        return await self._make_clip(persona, text, yields_floor=yields_floor)

    # -----------------------------------------------------------------------
    # Panel speaking loop
    # -----------------------------------------------------------------------

    async def _panel_loop(
        self,
        lead: Optional["asyncio.Task[Clip]"] = None,
        next_persona: Optional[Persona] = None,
        react: bool = False,
    ) -> None:
        """Run panelist turns until one hands the floor to the candidate.

        Each next turn is generated while the previous clip is still playing, and at most
        one clip waits queued on the client, so turns follow each other without dead air.
        """
        self.floor = "panel"
        self.is_ai_speaking = True
        prepared: Optional[asyncio.Task] = lead or asyncio.create_task(
            self._next_turn(next_persona, react=react)
        )
        first_turn_pending = lead is not None

        try:
            while self.is_active:
                try:
                    clip = await prepared
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # One failed turn must not stall the discussion.
                    logger.error("Panel turn generation failed: %s", exc)
                    await asyncio.sleep(0.5)
                    prepared = asyncio.create_task(self._next_turn())
                    continue
                await self._wait_for_outstanding(1)
                await self._dispatch(clip)

                if clip.yields_floor:
                    prepared = None
                    self._begin_handoff(clip)
                    await self._wait_for_outstanding(0)
                    await self._open_user_floor()
                    return

                if first_turn_pending:
                    prepared = asyncio.create_task(self._next_turn(next_persona, react=react))
                    first_turn_pending = False
                else:
                    prepared = asyncio.create_task(self._next_turn())
        except asyncio.CancelledError:
            if prepared is not None:
                prepared.cancel()

    async def _next_turn(self, persona: Optional[Persona] = None, react: bool = False) -> Clip:
        """Generate and synthesize the next panelist turn."""
        persona = persona or self._select_next_speaker()
        self.turns_since_user += 1
        yields = self.turns_since_user >= self.next_handoff_after
        mode = "react" if react else ("invite" if yields else "discuss")

        messages = persona.format_chat_messages(
            topic=self.topic,
            recent_transcripts=self.transcript,
            language=self.language,
            mode=mode,
            candidate_profile=self.candidate_profile,
        )
        try:
            raw = await get_sarvam_completion(messages=messages, temperature=0.7, max_tokens=120)
        except Exception as exc:
            logger.error("LLM generation failed for %s: %s", persona.name, exc)
            raw = MOCK_DEFAULT_REPLY
        text = self._clean_line(raw, persona) or MOCK_DEFAULT_REPLY

        if yields and "?" not in text:
            text = f"{text} {self._phrases['fallback_question']}"

        return await self._make_clip(persona, text, yields_floor=yields)

    async def _make_clip(
        self,
        persona: Persona,
        text: str,
        yields_floor: bool = False,
        record: bool = True,
    ) -> Clip:
        try:
            audio = await synthesize_speech(text=text, speaker=persona.avatar_id, language_code=self.language)
        except Exception as exc:
            # Send the line anyway: the client speaks placeholder audio with the browser's voice.
            logger.error("TTS failed for %s (%s); sending text with placeholder audio.", persona.name, exc)
            audio = MOCK_AUDIO_PAYLOAD
        return Clip(
            speaker=persona.name,
            avatar_id=persona.avatar_id,
            text=text,
            audio_base64=audio,
            duration=_clip_seconds(audio, text),
            yields_floor=yields_floor,
            record=record,
        )

    async def _dispatch(self, clip: Clip) -> None:
        """Send a clip to the client and record when it should finish playing."""
        self.turn_counter += 1
        clip.turn_id = self.turn_counter
        self.current_speaker = clip.speaker
        self.current_avatar_id = clip.avatar_id
        if clip.record:
            self.last_ai_speaker = clip.speaker

        if clip.record:
            timestamp = self._get_current_timestamp()
            self._append_transcript(clip.speaker, clip.text, timestamp)
            await self._send({
                "type": "transcript_update",
                "speaker": clip.speaker,
                "text": clip.text,
                "timestamp": timestamp,
                "turn_id": clip.turn_id,
            })

        await self._send({
            "type": "agent_speaking",
            "speaker": clip.speaker,
            "avatar_id": clip.avatar_id,
            "audio_base64": clip.audio_base64,
            "turn_id": clip.turn_id,
            "text": clip.text,
            "yields_floor": clip.yields_floor,
        })

        now = time.time()
        start = max(now, self.outstanding[-1].expected_end + SPEAKER_GAP_SECONDS) if self.outstanding else now
        self.outstanding.append(_Outstanding(clip.turn_id, start + clip.duration, clip.duration))

    def handle_playback_finished(self, turn_id: Any = None) -> None:
        """Client finished playing a clip (and every clip before it)."""
        try:
            done = int(turn_id)
        except (TypeError, ValueError):
            done = self.outstanding[0].turn_id if self.outstanding else 0
        while self.outstanding and self.outstanding[0].turn_id <= done:
            self.outstanding.popleft()
        self.playback_event.set()

    async def _wait_for_outstanding(self, max_queued: int) -> None:
        """Wait until at most `max_queued` clips are still playing or queued on the client."""
        while self.is_active and len(self.outstanding) > max_queued:
            head = self.outstanding[0]
            slack = max(PLAYBACK_SLACK_SECONDS, head.duration)
            timeout = head.expected_end + slack - time.time()
            if timeout <= 0:
                # Client never reported this clip; assume it finished.
                self.outstanding.popleft()
                continue
            self.playback_event.clear()
            try:
                await asyncio.wait_for(self.playback_event.wait(), timeout)
            except asyncio.TimeoutError:
                pass

    # -----------------------------------------------------------------------
    # Candidate floor
    # -----------------------------------------------------------------------

    def _begin_handoff(self, question: Clip) -> None:
        asker = next((p for p in self.panel if p.name == question.speaker), self.panel[0])
        self._cancel_handoff_prefetch()
        self.handoff = Handoff(
            asker=asker,
            question=question,
            # Prefetched so the check-in and acknowledgement play with no delay.
            check_in=asyncio.create_task(self._custom_clip(
                asker, INSTRUCTIONS["check_in"], self._phrases["check_in"], yields_floor=True
            )),
            ack=asyncio.create_task(
                self._make_clip(asker, random.choice(self._phrases["acks"]), record=False)
            ),
        )

    async def _set_floor(self, floor: str) -> None:
        self.floor = floor
        payload: Dict[str, Any] = {"type": "turn_update", "floor": floor}
        if floor == "user" and self.handoff:
            payload["speaker"] = self.handoff.asker.name
        await self._send(payload)

    async def _open_user_floor(self) -> None:
        """Hand the floor to the candidate and start the response timeout."""
        self.is_ai_speaking = False
        self.current_speaker = None
        self.current_avatar_id = None
        self.user_audio_buffer.clear()
        self.user_spoke.clear()
        await self._set_floor("user")
        self._cancel_task(self.user_turn_task)
        self.user_turn_task = asyncio.create_task(self._await_user_response())

    async def _await_user_response(self) -> None:
        """Check in if the candidate stays silent; move on if they still do."""
        handoff = self.handoff
        checked_in = handoff.checked_in if handoff else True
        timeout = settings.CHECKIN_REPLY_TIMEOUT if checked_in else settings.CANDIDATE_RESPONSE_TIMEOUT
        try:
            await asyncio.wait_for(self.user_spoke.wait(), timeout)
            return  # candidate started talking; end-of-turn detection takes over
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            return

        if not self.is_active or self.floor != "user":
            return

        if handoff and not handoff.checked_in:
            handoff.checked_in = True
            logger.info("No response after %.1fs; %s checks in.", timeout, handoff.asker.name)
            await self._set_floor("panel")
            self.is_ai_speaking = True
            self.active_turn_task = asyncio.create_task(self._speak_then_yield([handoff.check_in]))
            return

        logger.info("Still no response; the panel moves on.")
        await self._set_floor("panel")
        self._cancel_handoff_prefetch()
        self.handoff = None
        self._reset_handoff_cadence()
        move_on = None
        if handoff:
            move_on = asyncio.create_task(self._custom_clip(
                self.panel[0], INSTRUCTIONS["move_on"], self._phrases["move_on"]
            ))
        self.active_turn_task = asyncio.create_task(self._panel_loop(lead=move_on))

    async def _speak_then_yield(self, clips: List["asyncio.Future[Clip] | Clip"]) -> None:
        """Play short panel lines (the last one hands the floor back) and reopen the candidate's floor."""
        try:
            for item in clips:
                try:
                    clip = await item if isinstance(item, asyncio.Future) else item
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Could not prepare panel line: %s", exc)
                    continue
                await self._wait_for_outstanding(1)
                await self._dispatch(clip)
            await self._wait_for_outstanding(0)
            await self._open_user_floor()
        except asyncio.CancelledError:
            pass

    async def handle_audio_chunk(self, base64_data: str) -> None:
        """Ingest raw 16-bit PCM 16kHz mono audio while the candidate holds the floor."""
        if not self.is_active or not base64_data:
            return
        if self.floor != "user":
            return  # the panel holds the floor; ignore stray audio (echo, noise)

        try:
            pcm_chunk = base64.b64decode(base64_data)
        except Exception as exc:
            logger.error("Failed to decode base64 audio chunk: %s", exc)
            return

        self.user_audio_buffer.extend(pcm_chunk)
        self.last_candidate_speech_time = time.time()
        self.user_spoke.set()
        self._restart_pause_timer()

    def _restart_pause_timer(self) -> None:
        """Reset the end-of-turn timer; the turn ends after a short silence."""
        self._cancel_task(self.pause_timer_task)
        self.pause_timer_task = asyncio.create_task(self._pause_monitor())

    async def _pause_monitor(self) -> None:
        try:
            await asyncio.sleep(settings.USER_TURN_END_SILENCE)
        except asyncio.CancelledError:
            return
        if self.is_active and self.floor == "user":
            await self._finish_user_turn()

    async def _finish_user_turn(self) -> None:
        """Candidate stopped talking: acknowledge, transcribe, and decide what happens next."""
        await self._set_floor("panel")
        self._cancel_task(self.user_turn_task)
        handoff = self.handoff
        pcm = bytes(self.user_audio_buffer)
        self.user_audio_buffer.clear()

        # Long answers get an instant "Mm, okay." from the asker while transcription runs.
        if handoff and handoff.ack and len(pcm) >= ACK_MIN_ANSWER_SECONDS * PCM_BYTES_PER_SECOND:
            ack_task, handoff.ack = handoff.ack, None
            if ack_task.done() and not ack_task.cancelled() and ack_task.exception() is None:
                await self._dispatch(ack_task.result())
            else:
                ack_task.cancel()

        text = await self._transcribe(pcm)
        words = text.split()

        if handoff and not text:
            asker = handoff.asker
            self.active_turn_task = asyncio.create_task(self._speak_then_yield([
                asyncio.ensure_future(self._make_clip(asker, self._phrases["not_caught"], yields_floor=True)),
            ]))
            return

        if text and END_REQUEST.search(text) and len(words) <= 25:
            self._record_user(text)
            await self._send_user_transcript(text)
            self._cancel_handoff_prefetch()
            self.handoff = None
            self.active_turn_task = asyncio.create_task(self._wrap_up())
            return

        if handoff and REPEAT_REQUEST.search(text) and len(words) <= 12:
            self._record_user(text)
            await self._send_user_transcript(text)
            if self._llm_enabled():
                # Ask it again in simpler words rather than replaying it verbatim.
                rephrased = asyncio.ensure_future(self._custom_clip(
                    handoff.asker,
                    INSTRUCTIONS["rephrase"].format(question=handoff.question.text),
                    handoff.question.text,
                    yields_floor=True,
                ))
                self.active_turn_task = asyncio.create_task(self._speak_then_yield([rephrased]))
            else:
                intro = asyncio.ensure_future(self._make_clip(handoff.asker, self._phrases["repeat_intro"]))
                again = dataclasses.replace(handoff.question)
                self.active_turn_task = asyncio.create_task(self._speak_then_yield([intro, again]))
            return

        if handoff and handoff.checked_in and HEARING_CONFIRMATION.search(text) and len(words) <= 6:
            self._record_user(text)
            await self._send_user_transcript(text)
            self.active_turn_task = asyncio.create_task(self._speak_then_yield([
                asyncio.ensure_future(self._make_clip(handoff.asker, self._phrases["go_ahead"], yields_floor=True)),
            ]))
            return

        # A real answer: the panel responds to it.
        if text:
            self._record_user(text)
            await self._send_user_transcript(text)
        asker_name = handoff.asker.name if handoff else None
        self._cancel_handoff_prefetch()
        self.handoff = None
        self._reset_handoff_cadence()
        responder = self._select_next_speaker(exclude=asker_name) if text else None
        self.active_turn_task = asyncio.create_task(
            self._panel_loop(next_persona=responder, react=bool(text))
        )

    async def _wrap_up(self) -> None:
        """Candidate asked to stop for today: the moderator summarizes, then the report is sent."""
        self.is_ai_speaking = True
        try:
            await self._dispatch(await self._summary_clip(stopping_early=True))
            await self._wait_for_outstanding(0)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning("Summary failed: %s", exc)
        await self.end_session()

    async def handle_user_interrupted(self) -> None:
        """Legacy barge-in: stop the panel and give the candidate the floor."""
        if not self.is_active:
            return

        self.last_candidate_speech_time = time.time()

        if self.floor == "panel" and self.is_ai_speaking:
            interrupted_speaker = self.current_speaker
            logger.info("Interruption triggered against: %s", interrupted_speaker)

            self._cancel_task(self.active_turn_task)
            self.outstanding.clear()
            self.is_ai_speaking = False
            self.current_speaker = None
            self.current_avatar_id = None
            self.interruptions_handled += 1
            self._cancel_handoff_prefetch()
            self.handoff = None

            await self._send({
                "type": "agent_interrupted",
                "speaker": interrupted_speaker,
            })
            await self._open_user_floor()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _select_next_speaker(self, exclude: Optional[str] = None) -> Persona:
        """Select next AI speaker using weighted personality distribution."""
        avoid = exclude or self.last_ai_speaker
        candidates = [p for p in self.panel if p.name != avoid] or self.panel
        weights = [p.turn_weight for p in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]

    def _reset_handoff_cadence(self) -> None:
        self.turns_since_user = 0
        self.next_handoff_after = random.choice([2, 3, 3])

    def _cancel_handoff_prefetch(self) -> None:
        if self.handoff:
            for task in (self.handoff.check_in, self.handoff.ack):
                if task is not None and not task.done():
                    task.cancel()

    @staticmethod
    def _clean_line(raw: str, persona: Persona) -> str:
        """Strip reasoning tags, markdown, quotes, and speaker prefixes from an LLM line."""
        text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL)
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
        text = text.replace("<think>", "")
        text = re.sub(r"[*_#`]", "", text)
        text = re.sub(rf"^\s*{re.escape(persona.name)}\s*:\s*", "", text, flags=re.IGNORECASE)
        if ":" in text and len(text.split(":")[0]) < 15:
            text = text.split(":", 1)[1]
        text = " ".join(text.split()).strip().strip('"').strip()
        return text

    async def _transcribe(self, pcm: bytes) -> str:
        if not pcm:
            return ""
        try:
            text = await transcribe_audio_bytes(audio_bytes=pcm, language_code=self.language)
            return text.strip()
        except Exception as exc:
            logger.error("Error transcribing user audio via Sarvam STT: %s", exc)
            return ""

    async def _transcribe_and_record_buffer(self) -> None:
        if not self.user_audio_buffer:
            return
        pcm = bytes(self.user_audio_buffer)
        self.user_audio_buffer.clear()
        text = await self._transcribe(pcm)
        if text:
            self._record_user(text)
            await self._send_user_transcript(text)

    def _record_user(self, text: str) -> None:
        self.last_candidate_speech_time = time.time()
        self._append_transcript("User", text, self._get_current_timestamp())

    async def _send_user_transcript(self, text: str) -> None:
        await self._send({
            "type": "transcript_update",
            "speaker": "User",
            "text": text,
            "timestamp": self.transcript[-1]["timestamp"] if self.transcript else 0.0,
        })

    async def _run_timer_heartbeat(self) -> None:
        """Broadcast 'timer_tick' every second until session expiry."""
        try:
            while self.is_active and self.seconds_left > 0:
                await self._send({
                    "type": "timer_tick",
                    "seconds_left": self.seconds_left,
                })
                await asyncio.sleep(1.0)
                self.seconds_left -= 1

            if self.is_active and self.seconds_left <= 0:
                await self._send({"type": "timer_tick", "seconds_left": 0})
                await self._close_discussion()
        except asyncio.CancelledError:
            pass

    def _get_current_timestamp(self) -> float:
        """Get elapsed session time formatted to 1 decimal place."""
        if self.start_time <= 0:
            return 0.0
        return round(time.time() - self.start_time, 1)

    def _append_transcript(self, speaker: str, text: str, timestamp: float) -> None:
        """Record transcript entry."""
        self.transcript.append({
            "speaker": speaker,
            "text": text,
            "timestamp": timestamp,
        })

    async def _send(self, payload: Dict[str, Any]) -> None:
        """Safely send message to client callback."""
        try:
            await self.send_callback(payload)
        except Exception as exc:
            logger.error("Error delivering message to WebSocket: %s", exc)

    @staticmethod
    def _cancel_task(task: Optional[asyncio.Task]) -> None:
        """Cancel an asynchronous task safely (never the task that is calling this)."""
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()


def _describe_profile(profile: Optional[Dict[str, Any]]) -> str:
    """'works in Backend engineering; knows about Kafka, system design' from the lobby fields."""
    if not isinstance(profile, dict):
        return ""
    field = str(profile.get("field") or "").strip()[:80]
    interests = str(profile.get("interests") or "").strip()[:200]
    parts = []
    if field:
        parts.append(f"works in {field}")
    if interests:
        parts.append(f"knows about {interests}")
    return "; ".join(parts)


def _estimate_speech_seconds(text: str) -> float:
    # Roughly a browser voice's pace, which is what speaks placeholder (mock) audio.
    return max(1.2, len(text.split()) * 0.45)


def _clip_seconds(audio_base64: str, text: str) -> float:
    """Playback length of a clip: the WAV header's length, or a text-based estimate when the
    audio is a mock placeholder (the client speaks mock clips with the browser's voice)."""
    estimate = _estimate_speech_seconds(text)
    try:
        raw = base64.b64decode(audio_base64)
        with wave.open(io.BytesIO(raw)) as wav:
            seconds = wav.getnframes() / float(wav.getframerate())
    except Exception:
        return estimate
    if seconds < 0.6 * estimate or seconds > 3 * estimate + 5:
        return estimate
    return seconds
