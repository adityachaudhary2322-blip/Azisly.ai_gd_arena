"""Configuration module for GD Arena backend application."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base directory pointing to backend/
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Application settings backed by environment variables and .env file."""

    SARVAM_API_KEY: str = "your_sarvam_key_here"
    GEMINI_API_KEY: str = "your_gemini_key_here"
    MOCK_VOICE: bool = True
    PORT: int = 8000

    # Sarvam AI API endpoints
    SARVAM_STT_URL: str = "https://api.sarvam.ai/speech-to-text"
    SARVAM_TTS_URL: str = "https://api.sarvam.ai/text-to-speech"

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Return a cached instance of application settings."""
    return Settings()


settings = get_settings()
