"""Sarvam AI Text-to-Speech (TTS) Client Wrapper.

Synthesizes speech using Sarvam Bulbul v3 model (https://api.sarvam.ai/text-to-speech).
Maps the 5 GD Arena persona avatar_ids to exact Sarvam voice identifiers:
- moderator      -> 'arjun'
- dominator      -> 'shubh'
- data_driven    -> 'anushka'
- bridger        -> 'meera'
- quiet_analyst  -> 'arvind'

Guarantees valid standard WAV headers in the base64 output payload,
and provides clean data URI formatting (data:audio/wav;base64,{raw}).
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

# Live fallback for Bulbul v3 if server does not recognize legacy speaker names
BULBUL_FALLBACK_SPEAKERS: dict[str, str] = {
    "arjun": "aditya",
    "anushka": "kavya",
    "meera": "priya",
    "arvind": "rohan",
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


def wrap_pcm_in_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Encapsulate raw PCM bytes in a standard WAV header."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()


def ensure_wav_base64(raw_base64: str, sample_rate: int = 16000) -> str:
    """Ensure the returned base64 string includes valid standard WAV headers.

    If the payload is already a valid WAV (starts with RIFF and contains WAVE),
    it is returned cleanly. If it represents raw PCM or lacks headers, it is
    encapsulated in a standard 16-bit PCM mono WAV container.
    """
    if not raw_base64:
        return raw_base64

    clean_b64 = raw_base64.strip()
    if clean_b64.startswith("data:") and "," in clean_b64:
        clean_b64 = clean_b64.split(",", 1)[1]

    try:
        raw_bytes = base64.b64decode(clean_b64)
        if len(raw_bytes) >= 12 and raw_bytes.startswith(b"RIFF") and b"WAVE" in raw_bytes[:12]:
            return clean_b64

        # Wrap in valid WAV header
        wav_bytes = wrap_pcm_in_wav(raw_bytes, sample_rate=sample_rate)
        return base64.b64encode(wav_bytes).decode("utf-8")
    except Exception as exc:
        logger.warning("Failed to validate/encapsulate WAV header: %s", exc)
        return clean_b64


def to_audio_data_uri(base64_audio: str) -> str:
    """Format a clean base64 WAV string as a data URI: data:audio/wav;base64,{raw}."""
    clean = base64_audio.strip()
    if clean.startswith("data:"):
        return clean
    return f"data:audio/wav;base64,{clean}"


# Pre-computed mock silent WAV payload
MOCK_AUDIO_PAYLOAD: str = generate_mock_wav_base64()


async def synthesize_speech(
    text: str,
    speaker: str = "arjun",
    language_code: str = "en-IN",
    model: str = "bulbul:v3",
    pace: float = 1.0,
    as_data_uri: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Synthesize speech audio from text using Sarvam Bulbul v3 API.

    Args:
        text: Input text string to synthesize.
        speaker: Avatar ID ('moderator', 'dominator', 'data_driven', 'bridger', 'quiet_analyst')
                 or Sarvam voice identifier ('arjun', 'shubh', 'anushka', 'meera', 'arvind').
        language_code: Target Indic language code (e.g. 'en-IN', 'hi-IN', 'ta-IN', 'te-IN', 'bn-IN', 'kn-IN').
        model: Sarvam TTS model name (default: 'bulbul:v3').
        pace: Speech tempo between 0.5 and 2.0 (default: 1.0).
        as_data_uri: If True, returns formatted 'data:audio/wav;base64,{raw}'.
        client: Optional httpx.AsyncClient instance for testing / reuse.

    Returns:
        Base64-encoded audio string guaranteed to include valid WAV headers.

    Raises:
        httpx.HTTPStatusError: If Sarvam API responds with HTTP error status.
        httpx.RequestError: If network error occurs.
        ValueError: If no audio is returned in the API response.
    """
    if settings.MOCK_VOICE or not settings.SARVAM_API_KEY.strip():
        logger.debug("MOCK_VOICE active or missing API key. Returning mock base64 WAV payload.")
        wav_b64 = ensure_wav_base64(MOCK_AUDIO_PAYLOAD)
        return to_audio_data_uri(wav_b64) if as_data_uri else wav_b64

    if not text.strip():
        logger.warning("Empty text provided for speech synthesis.")
        wav_b64 = ensure_wav_base64(MOCK_AUDIO_PAYLOAD)
        return to_audio_data_uri(wav_b64) if as_data_uri else wav_b64

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
        "output_audio_codec": "wav",
    }

    async def _do_post(c: httpx.AsyncClient) -> str:
        response = await c.post(
            settings.SARVAM_TTS_URL,
            headers=headers,
            json=payload,
            timeout=30.0,
        )

        # If speaker is unrecognized on live API, fallback cleanly
        if response.status_code == 400 and "not recognized" in response.text:
            fallback = BULBUL_FALLBACK_SPEAKERS.get(resolved_speaker.lower())
            if fallback:
                logger.info("Bulbul v3 speaker '%s' unrecognized; retrying with '%s'", resolved_speaker, fallback)
                payload["speaker"] = fallback
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
        raw_output = audios[0]
        # Inspect and guarantee valid standard WAV headers
        valid_wav_b64 = ensure_wav_base64(raw_output)
        return to_audio_data_uri(valid_wav_b64) if as_data_uri else valid_wav_b64

    if client is not None:
        return await _do_post(client)

    async with httpx.AsyncClient() as default_client:
        return await _do_post(default_client)
