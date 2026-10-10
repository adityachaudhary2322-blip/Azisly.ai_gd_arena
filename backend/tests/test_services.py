"""Unit and integration tests for pure Sarvam AI services (STT, LLM, TTS) and config."""

import base64
import pytest
import httpx
from backend.config import Settings, settings, SUPPORTED_LANGUAGES
from backend.services.sarvam_stt import (
    transcribe_audio_bytes,
    pcm_to_wav_bytes,
    MOCK_TRANSCRIPTION,
)
from backend.services.sarvam_tts import (
    synthesize_speech,
    resolve_speaker,
    ensure_wav_base64,
    to_audio_data_uri,
    AVATAR_TO_VOICE_MAP,
    MOCK_AUDIO_PAYLOAD,
)
from backend.services.sarvam_llm import (
    get_sarvam_completion,
    _detect_mock_response,
    MOCK_PERSONA_DIALOGUE_EN,
    MOCK_PERSONA_DIALOGUE_HI,
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
    assert settings.CANDIDATE_SILENCE_THRESHOLD == 75.0
    assert "hi-IN" in SUPPORTED_LANGUAGES
    assert "ta-IN" in SUPPORTED_LANGUAGES


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
    transcript = await transcribe_audio_bytes(dummy_pcm, language_code="hi-IN")
    assert transcript == MOCK_TRANSCRIPTION


@pytest.mark.asyncio
async def test_sarvam_stt_api_success(monkeypatch):
    """Verify STT API call with Saaras v4 and Indic language code."""
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
        result = await transcribe_audio_bytes(b"dummy_pcm", language_code="ta-IN", client=client)
        assert result == expected_text


# ---------------------------------------------------------------------------
# Sarvam TTS & Voice Mapping Tests (5 Personas & WAV Headers)
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


def test_ensure_wav_base64_encapsulation():
    """Verify ensure_wav_base64 wraps raw PCM base64 into a valid WAV header."""
    # Raw PCM bytes without RIFF header
    raw_pcm = b"\x00\x00" * 800
    raw_b64 = base64.b64encode(raw_pcm).decode("utf-8")
    assert not raw_pcm.startswith(b"RIFF")

    wav_b64 = ensure_wav_base64(raw_b64)
    decoded_wav = base64.b64decode(wav_b64)
    assert decoded_wav.startswith(b"RIFF")
    assert b"WAVE" in decoded_wav[:12]

    # Data URI formatter
    data_uri = to_audio_data_uri(wav_b64)
    assert data_uri.startswith("data:audio/wav;base64,")


@pytest.mark.asyncio
async def test_sarvam_tts_mock_mode_all_personas():
    """Verify TTS returns valid base64 WAV payload with RIFF header for all 5 personas."""
    personas = ["moderator", "dominator", "data_driven", "bridger", "quiet_analyst"]
    for persona in personas:
        audio_b64 = await synthesize_speech(
            text="Let us analyze this problem.",
            speaker=persona,
            language_code="hi-IN",
        )
        assert audio_b64 == MOCK_AUDIO_PAYLOAD
        raw = base64.b64decode(audio_b64)
        assert raw.startswith(b"RIFF")
        assert b"WAVE" in raw[:12]

    # Test as data URI
    uri = await synthesize_speech(text="Hello", speaker="moderator", as_data_uri=True)
    assert uri.startswith("data:audio/wav;base64,")


@pytest.mark.asyncio
async def test_sarvam_tts_api_success(monkeypatch):
    """Verify TTS API call sends output_audio_codec='wav' and wraps raw audio if needed."""
    monkeypatch.setattr(settings, "MOCK_VOICE", False)
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "real-sarvam-key")

    # Simulate Bulbul output with valid WAV header
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 400)
    mock_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        import json
        assert str(request.url) == settings.SARVAM_TTS_URL
        assert request.headers.get("api-subscription-key") == "real-sarvam-key"
        body = json.loads(request.content)
        assert body["model"] == "bulbul:v3"
        assert body["speaker"] == "shubh"  # dominator -> shubh
        assert body["language_code"] == "hi-IN"
        assert body["output_audio_codec"] == "wav"
        return httpx.Response(200, json={"audios": [mock_b64]})

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await synthesize_speech("Speed is crucial.", speaker="dominator", language_code="hi-IN", client=client)
        assert result == mock_b64
        decoded = base64.b64decode(result)
        assert decoded.startswith(b"RIFF")


# ---------------------------------------------------------------------------
# Sarvam Chat / LLM Tests (Hinglish / Indic)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sarvam_llm_mock_dialogue_indic():
    """Verify Sarvam LLM returns deterministic Hindi/Hinglish persona dialogue in mock mode."""
    messages = [
        {"role": "system", "content": "You are Kabir, the Dominator. Strict Language Instruction: converse in Hindi / Hinglish."},
        {"role": "user", "content": "Respond to the topic in hi-IN."},
    ]
    reply = await get_sarvam_completion(messages)
    assert reply == MOCK_PERSONA_DIALOGUE_HI["dominator"]


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
