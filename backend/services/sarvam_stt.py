"""Sarvam AI Speech-to-Text (STT) Client Wrapper.

Wraps Sarvam's Saaras v4 model (https://api.sarvam.ai/speech-to-text).
Ingests 16-bit PCM 16kHz mono audio chunks, packages them into standard WAV containers,
and supports both 'en-IN' and 'hi-IN' language codes.
Includes instant mock bypass when MOCK_VOICE=True.
"""

import io
import logging
from typing import Optional
import wave
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

MOCK_TRANSCRIPTION = (
    "I believe artificial intelligence will significantly transform the job market, "
    "creating new opportunities while automating routine tasks."
)


def pcm_to_wav_bytes(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """Package raw 16-bit PCM mono audio data into a valid WAV format container."""
    if not pcm_data:
        return b""
    # If the payload is already an encapsulated WAV file, return as is
    if pcm_data.startswith(b"RIFF") and len(pcm_data) > 12:
        return pcm_data

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    language_code: str = "en-IN",
    model: str = "saaras:v4",
    mode: str = "transcribe",
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Transcribe raw audio bytes using Sarvam Saaras v4 API.

    Args:
        audio_bytes: Raw 16-bit PCM 16kHz mono bytes or WAV audio bytes.
        language_code: Target BCP-47 language code ('en-IN' or 'hi-IN').
        model: Sarvam STT model version (default: 'saaras:v4').
        mode: Transcription mode (default: 'transcribe').
        client: Optional httpx.AsyncClient instance for testing / reuse.

    Returns:
        The transcribed text string.

    Raises:
        httpx.HTTPStatusError: If the Sarvam API returns an HTTP error code.
        httpx.RequestError: If network/connection issues occur.
    """
    if settings.MOCK_VOICE or not settings.SARVAM_API_KEY.strip():
        logger.debug("MOCK_VOICE active or missing API key. Returning mock transcription.")
        return MOCK_TRANSCRIPTION

    if not audio_bytes:
        logger.warning("Empty audio bytes provided for transcription.")
        return ""

    # Ensure audio is properly packaged into a standard WAV container
    wav_payload = pcm_to_wav_bytes(audio_bytes)

    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
    }

    files = {
        "file": ("audio.wav", wav_payload, "audio/wav"),
    }

    data = {
        "model": model,
        "language_code": language_code,
        "mode": mode,
    }

    async def _do_post(c: httpx.AsyncClient) -> str:
        response = await c.post(
            settings.SARVAM_STT_URL,
            headers=headers,
            files=files,
            data=data,
            timeout=30.0,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("transcript", "")

    if client is not None:
        return await _do_post(client)

    async with httpx.AsyncClient() as default_client:
        return await _do_post(default_client)
