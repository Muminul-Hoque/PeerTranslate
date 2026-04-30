"""
PeerTranslate — Configuration Module

Handles environment variables, API keys, and application settings
using Pydantic for type-safe configuration.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(override=True)

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Supported languages with their display names and codes
SUPPORTED_LANGUAGES = {
    "bn": "বাংলা (Bengali)",
    "hi": "हिन्दी (Hindi)",
    "ta": "தமிழ் (Tamil)",
    "ur": "اردو (Urdu)",
    "es": "Español (Spanish)",
    "fr": "Français (French)",
    "de": "Deutsch (German)",
    "ja": "日本語 (Japanese)",
    "ko": "한국어 (Korean)",
    "zh": "中文 (Chinese)",
    "ar": "العربية (Arabic)",
    "pt": "Português (Portuguese)",
    "ru": "Русский (Russian)",
    "sw": "Kiswahili (Swahili)",
    "tr": "Türkçe (Turkish)",
}

# Supported academic domains for glossaries
SUPPORTED_DOMAINS = [
    "cs", "ml", "math", "statistics",
    "physics", "astronomy", "chemistry", "biology", "earth_sciences",
    "medicine", "engineering", "materials_science", "agriculture",
    "economics", "psychology", "sociology", "political_science",
    "law", "business", "linguistics", "general_academic"
]


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    )
    turso_database_url: str = field(
        default_factory=lambda: os.getenv("TURSO_DATABASE_URL", "")
    )
    turso_auth_token: str = field(
        default_factory=lambda: os.getenv("TURSO_AUTH_TOKEN", "")
    )
    similarity_threshold: float = field(
        default_factory=lambda: float(os.getenv("SIMILARITY_THRESHOLD", "0.96"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "2"))
    )
    max_file_size_mb: int = 50
    upload_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "uploads")

    def validate(self) -> None:
        """Validate that critical settings are present."""
        if not self.gemini_api_key or self.gemini_api_key == "your_gemini_api_key_here":
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Get your free key at: https://aistudio.google.com/apikey "
                "and add it to your .env file."
            )


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
