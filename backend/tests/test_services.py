"""Unit and integration tests for GD Arena Sarvam AI services and backend config."""

import base64
import pytest
import httpx
from backend.config import Settings, settings
from backend.services.sarvam_stt import transcribe_audio_bytes, MOCK_TRANSCRIPTION
from backend.services.sarvam_tts import (
    synthesize_speech,
    resolve_speaker,
    PERSONA_VOICE_MAP,
    MOCK_AUDIO_PAYLOAD,
)


# ---------------------------------------------------------------------------
# Configuration & Settings Tests
# ---------------------------------------------------------------------------

def test_settings_defaults():
    """Verify default configuration attributes are properly initialized."""
    assert settings.PORT == 8000
    assert settings.MOCK_VOICE is True
    assert settings.SARVAM_STT_URL == "https://api.sarvam.ai/speech-to-text"
    assert settings.SARVAM_TTS_URL == "https://api.sarvam.ai/text-to-speech"
    assert hasattr(settings, "SARVAM_API_KEY")
    assert hasattr(settings, "GEMINI_API_KEY")


# ---------------------------------------------------------------------------
# Persona Voice Mapping Tests
# ---------------------------------------------------------------------------

def test_persona_voice_resolution():
    """Verify that all 4 personas map to the correct Sarvam speaker voices."""
    assert resolve_speaker("Moderator") == "arjun"
    assert resolve_speaker("moderator") == "arjun"
    assert resolve_speaker("Dominator") == "shubh"
    assert resolve_speaker("dominator") == "shubh"
    assert resolve_speaker("Data-Driven") == "anushka"
    assert resolve_speaker("data-driven") == "anushka"
    assert resolve_speaker("Bridger") == "meera"
    assert resolve_speaker("bridger") == "meera"


def test_custom_or_direct_speaker_resolution():
    """Verify direct speaker names or custom names pass through correctly."""
    assert resolve_speaker("arjun") == "arjun"
    assert resolve_speaker("shubh") == "shubh"
    assert resolve_speaker("anushka") == "anushka"
    assert resolve_speaker("meera") == "meera"
    assert resolve_speaker("custom_voice") == "custom_voice"


# ---------------------------------------------------------------------------
# Mock Voice Mode Tests (MOCK_VOICE=True)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sarvam_stt_mock_mode():
    """Verify STT returns mock transcription without calling external API."""
    dummy_audio = b"\x00\x01\x02\x03" * 100
    transcript = await transcribe_audio_bytes(dummy_audio)
    assert transcript == MOCK_TRANSCRIPTION
    assert len(transcript) > 0


@pytest.mark.asyncio
async def test_sarvam_tts_mock_mode_all_personas():
    """Verify TTS returns valid mock base64 WAV audio for each persona."""
    personas = ["Moderator", "Dominator", "Data-Driven", "Bridger"]

    for persona in personas:
        audio_b64 = await synthesize_speech(
            text="Let us begin the group discussion on AI impact.",
            speaker=persona,
            language_code="en-IN",
        )
        assert audio_b64 == MOCK_AUDIO_PAYLOAD
        # Validate that payload decodes into a valid WAV header
        raw_wav = base64.b64decode(audio_b64)
        assert raw_wav.startswith(b"RIFF")
        assert b"WAVE" in raw_wav[:12]


@pytest.mark.asyncio
async def test_sarvam_tts_mock_mode_empty_text():
    """Verify TTS handles empty text in mock mode safely."""
    audio_b64 = await synthesize_speech(text="")
    assert audio_b64 == MOCK_AUDIO_PAYLOAD


# ---------------------------------------------------------------------------
# API Mode Tests (MOCK_VOICE=False with Mocked HTTP Responses)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sarvam_stt_api_success(monkeypatch):
    """Verify STT API call formatting and response parsing when MOCK_VOICE is False."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-sarvam-key")

    expected_transcript = "This is a real transcription from Sarvam Saaras v4."

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == settings.SARVAM_STT_URL
        assert request.headers.get("api-subscription-key") == "test-sarvam-key"
        assert "multipart/form-data" in request.headers.get("content-type", "")
        return httpx.Response(200, json={"transcript": expected_transcript})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        dummy_audio = b"RIFFdummywavbytes"
        result = await transcribe_audio_bytes(dummy_audio, client=client)
        assert result == expected_transcript


@pytest.mark.asyncio
async def test_sarvam_stt_api_error_handling(monkeypatch):
    """Verify STT raises HTTPStatusError on 401 Unauthorized."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "invalid-key")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid subscription key"})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        dummy_audio = b"RIFFdummywavbytes"
        with pytest.raises(httpx.HTTPStatusError):
            await transcribe_audio_bytes(dummy_audio, client=client)


@pytest.mark.asyncio
async def test_sarvam_tts_api_success_with_persona(monkeypatch):
    """Verify TTS API call maps 'Moderator' to 'arjun' and returns audio string."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test-sarvam-key")

    mock_base64_audio = "dGVzdF9hdWRpb19kYXRh"

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json
        assert str(request.url) == settings.SARVAM_TTS_URL
        assert request.headers.get("api-subscription-key") == "test-sarvam-key"
        assert request.headers.get("content-type") == "application/json"

        body = json.loads(request.content)
        assert body["model"] == "bulbul:v3"
        assert body["speaker"] == "arjun"  # Moderator -> arjun
        assert body["language_code"] == "en-IN"
        assert body["text"] == "Welcome participants to this discussion."

        return httpx.Response(200, json={"audios": [mock_base64_audio]})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await synthesize_speech(
            text="Welcome participants to this discussion.",
            speaker="Moderator",
            language_code="en-IN",
            client=client,
        )
        assert result == mock_base64_audio


@pytest.mark.asyncio
async def test_sarvam_tts_api_empty_audios_raises_value_error(monkeypatch):
    """Verify ValueError is raised if Sarvam TTS returns an empty audios array."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"audios": []})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="No audio data returned"):
            await synthesize_speech(
                text="Test prompt",
                speaker="Dominator",
                client=client,
            )
