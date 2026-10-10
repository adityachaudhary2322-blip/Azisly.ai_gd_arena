"""Turn-taking state machine and conversation orchestrator for GD Arena.

Features:
- Monitors conversational pauses with a strict 2.5s threshold.
- Dynamically assigns floor to AI speakers based on panel personas.
- Immediately halts active AI speech upon receiving 'user_interrupted' signal.
- Dispatches timer heartbeats ('timer_tick') and live transcript updates ('transcript_update').
- Concludes sessions with comprehensive metrics & verbatim evaluation ('final_report').
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
    MODERATOR,
    DOMINATOR,
    BRIDGER,
)
from backend.services.gemini_client import generate_persona_utterance
from backend.services.sarvam_stt import transcribe_audio_bytes
from backend.services.sarvam_tts import synthesize_speech

logger = logging.getLogger(__name__)

# Callback type for sending WebSocket messages to the client
SendCallback = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]

PAUSE_THRESHOLD_SECONDS = 2.5
DEFAULT_SESSION_SECONDS = 420


class GDOrchestrator:
    """State machine governing Group Discussion session dynamics and turn-taking."""

    def __init__(self, send_callback: SendCallback):
        self.send_callback = send_callback

        # Session attributes
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

        # Audio buffering & asynchronous tasks
        self.user_audio_buffer = bytearray()
        self.active_turn_task: Optional[asyncio.Task] = None
        self.pause_timer_task: Optional[asyncio.Task] = None
        self.timer_heartbeat_task: Optional[asyncio.Task] = None
        self.interrupt_event = asyncio.Event()

    # -----------------------------------------------------------------------
    # Message Dispatcher
    # -----------------------------------------------------------------------

    async def handle_client_message(self, message: Dict[str, Any]) -> None:
        """Process incoming WebSocket messages from client according to SCHEMA.md."""
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
            logger.warning("Unrecognized message type received: %s", msg_type)

    # -----------------------------------------------------------------------
    # Session Lifecycle
    # -----------------------------------------------------------------------

    async def start_session(
        self,
        topic: str = "AI in Job Markets",
        panel_size: int = 3,
        language: str = "en-IN",
    ) -> None:
        """Initialize and launch the GD session."""
        self.topic = topic
        self.panel_size = panel_size
        self.language = language
        self.panel = get_active_panel(panel_size)
        self.start_time = time.time()
        self.seconds_left = DEFAULT_SESSION_SECONDS
        self.is_active = True
        self.transcript.clear()
        self.interruptions_handled = 0
        self.user_audio_buffer.clear()
        self.last_ai_speaker = None
        self.is_ai_speaking = False

        logger.info(
            "Starting GD Session: topic='%s', panel_size=%d, language=%s",
            topic,
            panel_size,
            language,
        )

        # Start timer heartbeat
        self._cancel_task(self.timer_heartbeat_task)
        self.timer_heartbeat_task = asyncio.create_task(self._run_timer_heartbeat())

        # Moderator opens the discussion to establish structure
        moderator = next((p for p in self.panel if p.avatar_id == "moderator"), self.panel[0])
        self.active_turn_task = asyncio.create_task(
            self._execute_ai_turn(
                moderator,
                custom_text=(
                    f"Welcome everyone to this discussion on '{self.topic}'. "
                    "Let us examine both the opportunities and key challenges ahead."
                ),
            )
        )

    async def end_session(self) -> None:
        """Terminate the session and emit final evaluation report."""
        if not self.is_active:
            return

        self.is_active = False
        self._cancel_task(self.timer_heartbeat_task)
        self._cancel_task(self.pause_timer_task)
        self._cancel_task(self.active_turn_task)

        # Process any pending user audio in the buffer
        await self._flush_user_audio_buffer()

        report = await evaluate_session(
            transcripts=self.transcript,
            interruptions_count=self.interruptions_handled,
        )

        await self._send(report)
        logger.info("GD session concluded. Final report dispatched.")

    # -----------------------------------------------------------------------
    # Audio Chunk & Turn Detection
    # -----------------------------------------------------------------------

    async def handle_audio_chunk(self, base64_data: str) -> None:
        """Handle incoming user audio streaming chunk."""
        if not self.is_active or not base64_data:
            return

        try:
            raw_bytes = base64.b64decode(base64_data)
            self.user_audio_buffer.extend(raw_bytes)
        except Exception as exc:
            logger.error("Failed to decode base64 audio chunk: %s", exc)
            return

        # If user starts speaking while AI is speaking, treat as immediate interruption
        if self.is_ai_speaking:
            await self.handle_user_interrupted()

        # Reset pause monitoring timer (2.5s threshold)
        self._restart_pause_timer()

    async def handle_user_interrupted(self) -> None:
        """Handle 'user_interrupted' signal from client."""
        if not self.is_active:
            return

        if self.is_ai_speaking and self.current_speaker:
            interrupted_speaker = self.current_speaker
            logger.info("User interrupted AI speaker: %s", interrupted_speaker)

            # Signal cancellation to active speech task
            self.interrupt_event.set()
            self._cancel_task(self.active_turn_task)

            self.is_ai_speaking = False
            self.current_speaker = None
            self.current_avatar_id = None
            self.interruptions_handled += 1

            # Dispatch 'agent_interrupted' as per SCHEMA.md
            await self._send({
                "type": "agent_interrupted",
                "speaker": interrupted_speaker,
            })

            # Restart pause monitor so orchestrator listens for the user's interjection
            self._restart_pause_timer()

    def _restart_pause_timer(self) -> None:
        """Reset the 2.5s conversational pause timer."""
        self._cancel_task(self.pause_timer_task)
        self.pause_timer_task = asyncio.create_task(self._pause_monitor())

    async def _pause_monitor(self) -> None:
        """Wait for 2.5 seconds of silence, then trigger conversational turn."""
        try:
            await asyncio.sleep(PAUSE_THRESHOLD_SECONDS)
            if not self.is_active:
                return

            # Flush any accumulated user audio first
            await self._flush_user_audio_buffer()

            # Assign floor to next AI participant
            next_speaker = self._select_next_speaker()
            if next_speaker and not self.is_ai_speaking:
                self._cancel_task(self.active_turn_task)
                self.active_turn_task = asyncio.create_task(self._execute_ai_turn(next_speaker))

        except asyncio.CancelledError:
            pass

    async def _flush_user_audio_buffer(self) -> None:
        """Transcribe and append user audio buffer if content exists."""
        if not self.user_audio_buffer:
            return

        audio_bytes = bytes(self.user_audio_buffer)
        self.user_audio_buffer.clear()

        try:
            transcription = await transcribe_audio_bytes(
                audio_bytes=audio_bytes,
                language_code=self.language,
            )
            if transcription.strip():
                timestamp = self._get_current_timestamp()
                self._append_transcript("User", transcription, timestamp)
                await self._send({
                    "type": "transcript_update",
                    "speaker": "User",
                    "text": transcription,
                    "timestamp": timestamp,
                })
        except Exception as exc:
            logger.error("Error transcribing user audio: %s", exc)

    # -----------------------------------------------------------------------
    # AI Speaker Turn Execution
    # -----------------------------------------------------------------------

    def _select_next_speaker(self) -> Persona:
        """Select next AI speaker dynamically avoiding repetition."""
        available = [p for p in self.panel if p.name != self.last_ai_speaker]
        if not available:
            available = self.panel

        # Weighted selection based on persona dynamics
        weights = [p.turn_weight for p in available]
        chosen = random.choices(available, weights=weights, k=1)[0]
        return chosen

    async def _execute_ai_turn(
        self,
        persona: Persona,
        custom_text: Optional[str] = None,
    ) -> None:
        """Synthesize and stream dialogue for an AI participant."""
        self.interrupt_event.clear()
        self.is_ai_speaking = True
        self.current_speaker = persona.name
        self.current_avatar_id = persona.avatar_id
        self.last_ai_speaker = persona.name

        try:
            # 1. Generate text
            if custom_text:
                utterance_text = custom_text
            else:
                utterance_text = await generate_persona_utterance(
                    persona=persona,
                    topic=self.topic,
                    recent_transcripts=self.transcript,
                )

            timestamp = self._get_current_timestamp()
            self._append_transcript(persona.name, utterance_text, timestamp)

            # 2. Emit transcript update
            await self._send({
                "type": "transcript_update",
                "speaker": persona.name,
                "text": utterance_text,
                "timestamp": timestamp,
            })

            # 3. Synthesize audio
            audio_base64 = await synthesize_speech(
                text=utterance_text,
                speaker=persona.voice_speaker,
                language_code=self.language,
            )

            # 4. Emit agent_speaking message
            await self._send({
                "type": "agent_speaking",
                "speaker": persona.name,
                "avatar_id": persona.avatar_id,
                "audio_base64": audio_base64,
            })

            # 5. Simulate speaking duration with interruption vigilance
            word_count = len(utterance_text.split())
            speaking_duration = max(1.5, word_count * 0.3)

            elapsed = 0.0
            step = 0.1
            while elapsed < speaking_duration:
                if self.interrupt_event.is_set():
                    logger.info("Speech playback aborted mid-turn for %s", persona.name)
                    return
                await asyncio.sleep(step)
                elapsed += step

        except asyncio.CancelledError:
            logger.info("AI turn task cancelled for %s", persona.name)
            return
        except Exception as exc:
            logger.error("Error executing AI turn for %s: %s", persona.name, exc)
        finally:
            self.is_ai_speaking = False
            self.current_speaker = None
            self.current_avatar_id = None
            # If session is still active and no interruption occurred, initiate next pause window
            if self.is_active and not self.interrupt_event.is_set():
                self._restart_pause_timer()

    # -----------------------------------------------------------------------
    # Background Tasks & Helpers
    # -----------------------------------------------------------------------

    async def _run_timer_heartbeat(self) -> None:
        """Broadcast 'timer_tick' every second until session expiration."""
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
        """Get elapsed session time in seconds formatted to 1 decimal place."""
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
        """Send message safely through the provided send callback."""
        try:
            await self.send_callback(payload)
        except Exception as exc:
            logger.error("Error dispatching message to WebSocket client: %s", exc)

    @staticmethod
    def _cancel_task(task: Optional[asyncio.Task]) -> None:
        """Safely cancel an asynchronous task if running."""
        if task is not None and not task.done():
            task.cancel()
