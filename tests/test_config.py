"""
Unit tests for the PeerTranslate Config module.
"""

import pytest
from backend.config import Settings, get_settings, SUPPORTED_LANGUAGES, SUPPORTED_DOMAINS


class TestSettings:
    """Tests for the Settings dataclass."""

    def test_default_threshold(self):
        # Note: .env may override this. The code default is 0.96.
        settings = Settings()
        assert settings.similarity_threshold >= 0.85  # At minimum

    def test_max_file_size(self):
        settings = Settings()
        assert settings.max_file_size_mb == 50

    def test_max_retries(self):
        settings = Settings()
        assert settings.max_retries >= 1

    def test_validate_missing_key(self):
        settings = Settings(gemini_api_key="")
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            settings.validate()

    def test_validate_placeholder_key(self):
        settings = Settings(gemini_api_key="your_gemini_api_key_here")
        with pytest.raises(ValueError):
            settings.validate()


class TestSupportedLanguages:
    """Tests for language configuration."""

    def test_bengali_present(self):
        assert "bn" in SUPPORTED_LANGUAGES

    def test_at_least_10_languages(self):
        assert len(SUPPORTED_LANGUAGES) >= 10

    def test_all_have_display_names(self):
        for code, name in SUPPORTED_LANGUAGES.items():
            assert len(name) > 0
            assert "(" in name  # Format: "নাম (Name)"


class TestSupportedDomains:
    """Tests for domain configuration."""

    def test_required_domains(self):
        assert "cs" in SUPPORTED_DOMAINS
        assert "ml" in SUPPORTED_DOMAINS
        assert "general_academic" in SUPPORTED_DOMAINS
