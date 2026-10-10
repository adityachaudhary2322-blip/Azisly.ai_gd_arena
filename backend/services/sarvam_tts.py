"""Sarvam AI Text-to-Speech (TTS) Client Wrapper.

Synthesizes speech using Sarvam Bulbul v3 model (https://api.sarvam.ai/text-to-speech).
Maps the 5 GD Arena persona avatar_ids to exact Sarvam voice identifiers:
- moderator      -> 'arjun'
- dominator      -> 'shubh'
- data_driven    -> 'anushka'
- bridger        -> 'meera'
- quiet_analyst  -> 'arvind'

Returns raw base64 audio payload matching SCHEMA.md agent_speaking.
Includes a dummy silent WAV mock mode when MOCK_VOICE=True or missing API key.
"""

import base64
import io
import logging
from typing import Optional
import wave
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Avatar ID / Persona name to Sarvam voice identifier mapping
AVATAR_TO_VOICE_MAP: dict[str, str] = {
    # Avatar identifiers
    "moderator": "arjun",
    "dominator": "shubh",
    "data_driven": "anushka",
    "data-driven": "anushka",
    "bridger": "meera",
    "quiet_analyst": "arvind",
    "quiet-analyst": "arvind",
    # Persona character names
    "arjun": "arjun",
    "kabir": "shubh",
    "shubh": "shubh",
    "anushka": "anushka",
    "priya": "meera",
    "meera": "meera",
    "rohan": "arvind",
    "arvind": "arvind",
}


def resolve_speaker(avatar_id_or_speaker: str) -> str:
    """Resolve avatar identifier or persona name to an exact Sarvam speaker voice."""
    key = avatar_id_or_speaker.strip().lower()
    return AVATAR_TO_VOICE_MAP.get(key, avatar_id_or_speaker)


def generate_mock_wav_base64(duration_seconds: float = 0.5, sample_rate: int = 16000) -> str:
    """Generate a valid silent mono 16-bit PCM WAV payload encoded in base64."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(sample_rate)
        total_frames = int(sample_rate * duration_seconds)
        wav_file.writeframes(b"\x00\x00" * total_frames)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# Pre-computed mock silent WAV payload
MOCK_AUDIO_PAYLOAD: str = generate_mock_wav_base64()


async def synthesize_speech(
    text: str,
    speaker: str = "arjun",
    language_code: str = "en-IN",
    model: str = "bulbul:v3",
    pace: float = 1.0,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Synthesize speech audio from text using Sarvam Bulbul v3 API.

    Args:
        text: Input text string to synthesize.
        speaker: Avatar ID ('moderator', 'dominator', 'data_driven', 'bridger', 'quiet_analyst')
                 or Sarvam voice identifier ('arjun', 'shubh', 'anushka', 'meera', 'arvind').
        language_code: Target BCP-47 language code (default: 'en-IN').
        model: Sarvam TTS model name (default: 'bulbul:v3').
        pace: Speech tempo between 0.5 and 2.0 (default: 1.0).
        client: Optional httpx.AsyncClient instance for testing / reuse.

    Returns:
        Base64-encoded audio string from response audios[0] matching SCHEMA.md.

    Raises:
        httpx.HTTPStatusError: If Sarvam API responds with HTTP error status.
        httpx.RequestError: If network error occurs.
        ValueError: If no audio is returned in the API response.
    """
    if settings.MOCK_VOICE or not settings.SARVAM_API_KEY.strip():
        logger.debug("MOCK_VOICE active or missing API key. Returning mock base64 WAV payload.")
        return MOCK_AUDIO_PAYLOAD

    if not text.strip():
        logger.warning("Empty text provided for speech synthesis.")
        return MOCK_AUDIO_PAYLOAD

    resolved_speaker = resolve_speaker(speaker)

    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "language_code": language_code,
        "model": model,
        "speaker": resolved_speaker,
        "pace": pace,
    }

    async def _do_post(c: httpx.AsyncClient) -> str:
        response = await c.post(
            settings.SARVAM_TTS_URL,
            headers=headers,
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        audios = data.get("audios", [])
        if not audios:
            raise ValueError(f"No audio data returned by Sarvam TTS API: {data}")
        return audios[0]

    if client is not None:
        return await _do_post(client)

    async with httpx.AsyncClient() as default_client:
        return await _do_post(default_client)
