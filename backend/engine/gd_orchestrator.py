"""Turn-taking state machine and multi-agent conversation orchestrator for GD Arena.

100% Sarvam AI powered (Saaras STT, Sarvam LLM, Bulbul TTS):
- Tracks elapsed time, conversational floor state, and speaker timestamps.
- Generates in-character responses via sarvam_llm.py and synthesizes audio via sarvam_tts.py.
- Immediate interruption control: sets an abort flag to halt active agent speech on 'user_interrupted'.
- Activates first N personas (3 to 5) based on panel size.
- Strictly adheres to SCHEMA.md contract.
"""

import asyncio
import base64
import logging
import random
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

from backend.config import settings
from backend.engine.evaluator import evaluate_session
from backend.engine.personas import (
    Persona,
    get_active_panel,
    get_persona_by_id,
)
from backend.services.sarvam_llm import get_sarvam_completion
from backend.services.sarvam_stt import transcribe_audio_bytes
from backend.services.sarvam_tts import synthesize_speech

logger = logging.getLogger(__name__)

SendCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]

PAUSE_THRESHOLD_SECONDS = 2.5
DEFAULT_SESSION_SECONDS = 420


class GDOrchestrator:
    """State machine governing multi-agent Group Discussion session dynamics."""

    def __init__(self, send_callback: SendCallback):
        self.send_callback = send_callback

        # Session configuration
        self.topic: str = "Campus Recruitment Discussion"
        self.panel_size: int = 3
        self.language: str = "en-IN"
        self.panel: List[Persona] = []
        self.start_time: float = 0.0
        self.seconds_left: int = DEFAULT_SESSION_SECONDS
        self.is_active: bool = False

        # Conversational state
        self.transcript: List[Dict[str, Any]] = []
        self.current_speaker: Optional[str] = None
        self.current_avatar_id: Optional[str] = None
        self.is_ai_speaking: bool = False
        self.last_ai_speaker: Optional[str] = None
        self.interruptions_handled: int = 0

        # Audio buffering (16-bit PCM 16kHz mono chunks)
        self.user_audio_buffer = bytearray()

        # Asynchronous tasks and interruption flags
        self.active_turn_task: Optional[asyncio.Task] = None
        self.pause_timer_task: Optional[asyncio.Task] = None
        self.timer_heartbeat_task: Optional[asyncio.Task] = None
        self.interrupt_event = asyncio.Event()

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
            )
        elif msg_type == "audio_chunk":
            await self.handle_audio_chunk(message.get("data", ""))
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
    ) -> None:
        """Initialize session and activate the first N panel personas."""
        self.topic = topic
        self.panel_size = max(3, min(5, panel_size))
        self.language = language
        self.panel = get_active_panel(self.panel_size)
        self.start_time = time.time()
        self.seconds_left = DEFAULT_SESSION_SECONDS
        self.is_active = True
        self.transcript.clear()
        self.interruptions_handled = 0
        self.user_audio_buffer.clear()
        self.last_ai_speaker = None
        self.is_ai_speaking = False

        logger.info(
            "Session initiated: topic='%s', panel_size=%d (%s), language=%s",
            self.topic,
            len(self.panel),
            [p.name for p in self.panel],
            self.language,
        )

        # Start timer heartbeat broadcasting timer_tick every second
        self._cancel_task(self.timer_heartbeat_task)
        self.timer_heartbeat_task = asyncio.create_task(self._run_timer_heartbeat())

        # Moderator delivers opening structure
        moderator = self.panel[0]
        opening_prompt = (
            f"Welcome to this group discussion on '{self.topic}'. "
            "Let us establish a balanced framework examining both technological potential and socioeconomic impact."
        )
        self.active_turn_task = asyncio.create_task(
            self._execute_ai_turn(moderator, forced_text=opening_prompt)
        )

    async def end_session(self) -> None:
        """Conclude session, compute metrics, and dispatch final_report."""
        if not self.is_active:
            return

        self.is_active = False
        self._cancel_task(self.timer_heartbeat_task)
        self._cancel_task(self.pause_timer_task)
        self._cancel_task(self.active_turn_task)

        # Flush any remaining speech buffer
        await self._flush_user_audio_buffer()

        report = await evaluate_session(
            transcripts=self.transcript,
            interruptions_count=self.interruptions_handled,
        )

        await self._send(report)
        logger.info("Session ended. Dispatched final_report matching SCHEMA.md.")

    # -----------------------------------------------------------------------
    # Audio Ingestion & Pause Monitoring
    # -----------------------------------------------------------------------

    async def handle_audio_chunk(self, base64_data: str) -> None:
        """Ingest raw 16-bit PCM 16kHz mono audio chunk from frontend."""
        if not self.is_active or not base64_data:
            return

        try:
            pcm_chunk = base64.b64decode(base64_data)
            self.user_audio_buffer.extend(pcm_chunk)
        except Exception as exc:
            logger.error("Failed to decode base64 audio chunk: %s", exc)
            return

        # If user speaks during an AI turn, trigger immediate interruption
        if self.is_ai_speaking:
            await self.handle_user_interrupted()

        # Restart 2.5s conversational pause timer
        self._restart_pause_timer()

    async def handle_user_interrupted(self) -> None:
        """Handle user_interrupted signal from client immediately."""
        if not self.is_active:
            return

        if self.is_ai_speaking and self.current_speaker:
            interrupted_speaker = self.current_speaker
            logger.info("Interruption triggered against: %s", interrupted_speaker)

            # Abort active turn task immediately to drop audio
            self.interrupt_event.set()
            self._cancel_task(self.active_turn_task)

            self.is_ai_speaking = False
            self.current_speaker = None
            self.current_avatar_id = None
            self.interruptions_handled += 1

            # Dispatch agent_interrupted message as per SCHEMA.md
            await self._send({
                "type": "agent_interrupted",
                "speaker": interrupted_speaker,
            })

            # Monitor silence following the interruption
            self._restart_pause_timer()

    def _restart_pause_timer(self) -> None:
        """Reset the 2.5s pause monitoring timer."""
        self._cancel_task(self.pause_timer_task)
        self.pause_timer_task = asyncio.create_task(self._pause_monitor())

    async def _pause_monitor(self) -> None:
        """Wait for 2.5 seconds of silence, then trigger conversational turn."""
        try:
            await asyncio.sleep(PAUSE_THRESHOLD_SECONDS)
            if not self.is_active:
                return

            # Transcribe accumulated user PCM bytes
            await self._flush_user_audio_buffer()

            # Assign floor to next AI participant
            next_persona = self._select_next_speaker()
            if next_persona and not self.is_ai_speaking:
                self._cancel_task(self.active_turn_task)
                self.active_turn_task = asyncio.create_task(self._execute_ai_turn(next_persona))

        except asyncio.CancelledError:
            pass

    async def _flush_user_audio_buffer(self) -> None:
        """Transcribe accumulated PCM audio via Sarvam Saaras STT and append to transcript."""
        if not self.user_audio_buffer:
            return

        pcm_bytes = bytes(self.user_audio_buffer)
        self.user_audio_buffer.clear()

        try:
            transcription = await transcribe_audio_bytes(
                audio_bytes=pcm_bytes,
                language_code=self.language,
            )
            clean_text = transcription.strip()
            if clean_text:
                timestamp = self._get_current_timestamp()
                self._append_transcript("User", clean_text, timestamp)
                await self._send({
                    "type": "transcript_update",
                    "speaker": "User",
                    "text": clean_text,
                    "timestamp": timestamp,
                })
        except Exception as exc:
            logger.error("Error transcribing user audio via Sarvam STT: %s", exc)

    # -----------------------------------------------------------------------
    # Dynamic Turn Taking & AI Execution
    # -----------------------------------------------------------------------

    def _select_next_speaker(self) -> Persona:
        """Select next AI speaker using weighted personality distribution."""
        candidates = [p for p in self.panel if p.name != self.last_ai_speaker]
        if not candidates:
            candidates = self.panel

        weights = [p.turn_weight for p in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]

    async def _execute_ai_turn(
        self,
        persona: Persona,
        forced_text: Optional[str] = None,
    ) -> None:
        """Generate dialogue via Sarvam LLM and synthesize voice via Sarvam TTS."""
        self.interrupt_event.clear()
        self.is_ai_speaking = True
        self.current_speaker = persona.name
        self.current_avatar_id = persona.avatar_id
        self.last_ai_speaker = persona.name

        try:
            # 1. Generate text using Sarvam Chat completions
            if forced_text:
                dialogue_text = forced_text
            else:
                messages = persona.format_chat_messages(
                    topic=self.topic,
                    recent_transcripts=self.transcript,
                )
                dialogue_text = await get_sarvam_completion(
                    messages=messages,
                    temperature=0.2,
                    max_tokens=60,
                )

                # Clean any accidental speaker prefixes
                if ":" in dialogue_text and len(dialogue_text.split(":")[0]) < 15:
                    dialogue_text = dialogue_text.split(":", 1)[1].strip()

            timestamp = self._get_current_timestamp()
            self._append_transcript(persona.name, dialogue_text, timestamp)

            # 2. Dispatch transcript update as per SCHEMA.md
            await self._send({
                "type": "transcript_update",
                "speaker": persona.name,
                "text": dialogue_text,
                "timestamp": timestamp,
            })

            # 3. Synthesize speech via Sarvam Bulbul v3 TTS
            audio_base64 = await synthesize_speech(
                text=dialogue_text,
                speaker=persona.avatar_id,
                language_code=self.language,
            )

            # 4. Dispatch agent_speaking message as per SCHEMA.md
            await self._send({
                "type": "agent_speaking",
                "speaker": persona.name,
                "avatar_id": persona.avatar_id,
                "audio_base64": audio_base64,
            })

            # 5. Playback duration simulation with abort vigilance
            word_count = len(dialogue_text.split())
            duration = max(1.5, word_count * 0.28)
            elapsed = 0.0
            step = 0.1

            while elapsed < duration:
                if self.interrupt_event.is_set():
                    logger.info("Playback aborted mid-speech for %s", persona.name)
                    return
                await asyncio.sleep(step)
                elapsed += step

        except asyncio.CancelledError:
            logger.info("AI turn task cancelled for %s", persona.name)
            return
        except Exception as exc:
            logger.error("Error during AI turn for %s: %s", persona.name, exc)
        finally:
            self.is_ai_speaking = False
            self.current_speaker = None
            self.current_avatar_id = None
            if self.is_active and not self.interrupt_event.is_set():
                self._restart_pause_timer()

    # -----------------------------------------------------------------------
    # Background Tasks & Helpers
    # -----------------------------------------------------------------------

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
                await self.end_session()
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
        """Cancel an asynchronous task safely."""
        if task is not None and not task.done():
            task.cancel()
