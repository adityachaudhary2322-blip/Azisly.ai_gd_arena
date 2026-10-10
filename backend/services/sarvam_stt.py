"""Sarvam AI Speech-to-Text (STT) Client Wrapper.

Provides transcription capabilities using Sarvam AI's Saaras v4 model.
Supports mock voice transcription to conserve API credits during testing/development.
"""

import logging
from typing import Optional
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

MOCK_TRANSCRIPTION = (
    "I believe artificial intelligence will significantly transform the job market, "
    "creating new opportunities while automating routine tasks."
)


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    language_code: str = "en-IN",
    model: str = "saaras:v4",
    mode: str = "transcribe",
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Transcribe raw audio bytes using Sarvam Saaras v4 API.

    Args:
        audio_bytes: Raw audio byte content (e.g. WAV/MP3 format).
        language_code: Target BCP-47 language code (default: 'en-IN').
        model: Sarvam STT model version (default: 'saaras:v4').
        mode: Transcription mode (default: 'transcribe').
        client: Optional httpx.AsyncClient instance for connection pooling / testing.

    Returns:
        The transcribed text string.

    Raises:
        httpx.HTTPStatusError: If the Sarvam API returns an HTTP error code.
        httpx.RequestError: If network/connection issues occur.
    """
    if settings.MOCK_VOICE:
        logger.info("MOCK_VOICE is enabled. Returning mock transcription.")
        return MOCK_TRANSCRIPTION

    if not audio_bytes:
        logger.warning("Empty audio bytes provided for transcription.")
        return ""

    headers = {
        "api-subscription-key": settings.SARVAM_API_KEY,
    }

    files = {
        "file": ("audio.wav", audio_bytes, "audio/wav"),
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
