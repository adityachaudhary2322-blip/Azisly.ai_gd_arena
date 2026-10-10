"""Configuration module for GD Arena backend application.

100% pure Sarvam AI ecosystem integration (STT, LLM, TTS).
Production-ready configuration for Render deployment.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Set
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory pointing to backend/
BASE_DIR = Path(__file__).resolve().parent

SUPPORTED_LANGUAGES: Set[str] = {
    "en-IN",
    "en-US",  # American English dialogue; Sarvam speech runs as en-IN
    "hinglish",  # Hindi + English mix in Roman script; Sarvam speech runs as hi-IN
    "hi-IN",
    "ta-IN",
    "te-IN",
    "bn-IN",
    "kn-IN",
}


class Settings(BaseSettings):
    """Application settings backed by environment variables and .env file."""

    SARVAM_API_KEY: str = ""
    MOCK_VOICE: bool = False
    PORT: int = int(os.getenv("PORT", 8000))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Sarvam AI API endpoints
    SARVAM_STT_URL: str = "https://api.sarvam.ai/speech-to-text"
    SARVAM_TTS_URL: str = "https://api.sarvam.ai/text-to-speech"
    SARVAM_LLM_URL: str = "https://api.sarvam.ai/v1/chat/completions"
    SARVAM_LLM_MODEL: str = "sarvam-2b"

    # GD Engine Parameters
    PAUSE_THRESHOLD: float = 2.5
    DEFAULT_SESSION_DURATION: int = 420
    CANDIDATE_SILENCE_THRESHOLD: float = 75.0  # legacy; the turn engine now uses the floor timeouts below

    # Floor handoff: the candidate speaks only when a panelist asks them to.
    CANDIDATE_RESPONSE_TIMEOUT: float = 1.5  # silence after a question before "can you hear me?"
    CHECKIN_REPLY_TIMEOUT: float = 6.0  # silence after the check-in before the panel moves on
    USER_TURN_END_SILENCE: float = 0.8  # gap after the last audio chunk that ends the candidate's turn

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def model_post_init(self, __context: Any) -> None:
        """Safely fallback to mock mode if SARVAM_API_KEY is missing or placeholder."""
        key = self.SARVAM_API_KEY.strip()
        if not key or key in ("your_sarvam_key_here", "your_key_here"):
            self.MOCK_VOICE = True


@lru_cache()
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()


settings = get_settings()
