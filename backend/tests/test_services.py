"""Unit and integration tests for pure Sarvam AI services (STT, LLM, TTS) and config."""

import base64
import pytest
import httpx
from backend.config import Settings, settings
from backend.services.sarvam_stt import (
    transcribe_audio_bytes,
    pcm_to_wav_bytes,
    MOCK_TRANSCRIPTION,
)
from backend.services.sarvam_tts import (
    synthesize_speech,
    resolve_speaker,
    AVATAR_TO_VOICE_MAP,
    MOCK_AUDIO_PAYLOAD,
)
from backend.services.sarvam_llm import (
    get_sarvam_completion,
    _detect_mock_response,
    MOCK_PERSONA_DIALOGUE,
)


# ---------------------------------------------------------------------------
# Configuration & Settings Tests
# ---------------------------------------------------------------------------

def test_settings_pure_sarvam_defaults():
    """Verify settings loads Sarvam keys and defaults safely without third-party LLMs."""
    assert settings.PORT == 8000
    assert hasattr(settings, "SARVAM_API_KEY")
    assert not hasattr(settings, "GEMINI_API_KEY")
    assert not hasattr(settings, "OPENAI_API_KEY")
    assert settings.SARVAM_STT_URL == "https://api.sarvam.ai/speech-to-text"
    assert settings.SARVAM_TTS_URL == "https://api.sarvam.ai/text-to-speech"
    assert settings.SARVAM_LLM_URL == "https://api.sarvam.ai/v1/chat/completions"


def test_settings_empty_env_fallback():
    """Verify missing or placeholder key safely activates mock mode."""
    test_settings = Settings(SARVAM_API_KEY="")
    assert test_settings.MOCK_VOICE is True

    placeholder_settings = Settings(SARVAM_API_KEY="your_sarvam_key_here")
    assert placeholder_settings.MOCK_VOICE is True


# ---------------------------------------------------------------------------
# Sarvam STT Tests
# ---------------------------------------------------------------------------

def test_pcm_to_wav_bytes():
    """Verify raw PCM audio is properly encapsulated in a standard WAV container."""
    dummy_pcm = b"\x00\x01\x02\x03" * 200
    wav = pcm_to_wav_bytes(dummy_pcm)
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav[:12]

    # Passing already-wrapped WAV should return untouched
    assert pcm_to_wav_bytes(wav) == wav


@pytest.mark.asyncio
async def test_sarvam_stt_mock_mode():
    """Verify STT returns mock transcription in mock mode."""
    dummy_pcm = b"\x00\x01\x02\x03" * 100
    transcript = await transcribe_audio_bytes(dummy_pcm, language_code="en-IN")
    assert transcript == MOCK_TRANSCRIPTION


@pytest.mark.asyncio
async def test_sarvam_stt_api_success(monkeypatch):
    """Verify STT API call with Saaras v4 and multipart payload."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "real-sarvam-key")

    expected_text = "Transcription from Sarvam Saaras v4."

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == settings.SARVAM_STT_URL
        assert request.headers.get("api-subscription-key") == "real-sarvam-key"
        assert "multipart/form-data" in request.headers.get("content-type", "")
        return httpx.Response(200, json={"transcript": expected_text})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await transcribe_audio_bytes(b"dummy_pcm", client=client)
        assert result == expected_text


# ---------------------------------------------------------------------------
# Sarvam TTS & Voice Mapping Tests (5 Personas)
# ---------------------------------------------------------------------------

def test_sarvam_tts_voice_resolution():
    """Verify all 5 personas map to exact Sarvam voice identifiers."""
    assert resolve_speaker("moderator") == "arjun"
    assert resolve_speaker("dominator") == "shubh"
    assert resolve_speaker("data_driven") == "anushka"
    assert resolve_speaker("data-driven") == "anushka"
    assert resolve_speaker("bridger") == "meera"
    assert resolve_speaker("quiet_analyst") == "arvind"
    assert resolve_speaker("quiet-analyst") == "arvind"

    # Name-based resolution
    assert resolve_speaker("Arjun") == "arjun"
    assert resolve_speaker("Kabir") == "shubh"
    assert resolve_speaker("Anushka") == "anushka"
    assert resolve_speaker("Priya") == "meera"
    assert resolve_speaker("Rohan") == "arvind"


@pytest.mark.asyncio
async def test_sarvam_tts_mock_mode_all_personas():
    """Verify TTS returns valid base64 WAV payload for all 5 personas."""
    personas = ["moderator", "dominator", "data_driven", "bridger", "quiet_analyst"]
    for persona in personas:
        audio_b64 = await synthesize_speech(
            text="Let us analyze this problem.",
            speaker=persona,
            language_code="en-IN",
        )
        assert audio_b64 == MOCK_AUDIO_PAYLOAD
        raw = base64.b64decode(audio_b64)
        assert raw.startswith(b"RIFF")


@pytest.mark.asyncio
async def test_sarvam_tts_api_success(monkeypatch):
    """Verify TTS API call sends correct speaker and Bulbul v3 model."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "real-sarvam-key")

    mock_b64 = "dGVzdF9hdWRpb19kYXRh"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json
        assert str(request.url) == settings.SARVAM_TTS_URL
        assert request.headers.get("api-subscription-key") == "real-sarvam-key"
        body = json.loads(request.content)
        assert body["model"] == "bulbul:v3"
        assert body["speaker"] == "shubh"  # dominator -> shubh
        return httpx.Response(200, json={"audios": [mock_b64]})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await synthesize_speech("Speed is crucial.", speaker="dominator", client=client)
        assert result == mock_b64


# ---------------------------------------------------------------------------
# Sarvam Chat / LLM Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sarvam_llm_mock_dialogue():
    """Verify Sarvam LLM returns deterministic persona dialogue in mock mode."""
    messages = [
        {"role": "system", "content": "You are Kabir, the Dominator."},
        {"role": "user", "content": "Respond to the topic."},
    ]
    reply = await get_sarvam_completion(messages)
    assert reply == MOCK_PERSONA_DIALOGUE["dominator"]


@pytest.mark.asyncio
async def test_sarvam_llm_api_success(monkeypatch):
    """Verify Sarvam Chat completions API format and response parsing."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "real-sarvam-key")

    expected_output = "This is a completion from Sarvam-2B."

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json
        assert str(request.url) == settings.SARVAM_LLM_URL
        assert request.headers.get("api-subscription-key") == "real-sarvam-key"
        body = json.loads(request.content)
        assert body["model"] == "sarvam-2b"
        return httpx.Response(200, json={
            "choices": [
                {"message": {"content": expected_output}}
            ]
        })

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await get_sarvam_completion([{"role": "user", "content": "Hello"}], client=client)
        assert result == expected_output
