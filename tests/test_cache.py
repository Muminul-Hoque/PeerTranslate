"""
Unit tests for the Translation Cache module.
"""

import pytest
import os
import sqlite3
from backend.cache import (
    get_cached_translation,
    save_translation,
    flag_translation,
    get_hash,
    CACHE_DB_PATH
)

@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure a clean database before each test."""
    # Delete the DB file if it exists so we start fresh
    if os.path.exists(CACHE_DB_PATH):
        try:
            os.remove(CACHE_DB_PATH)
        except PermissionError:
            pass
    yield
    # Cleanup after
    if os.path.exists(CACHE_DB_PATH):
        try:
            os.remove(CACHE_DB_PATH)
        except OSError:
            pass


class TestCache:
    """Tests for the SQLite Cache module."""

    def test_cache_miss(self):
        """Should return None for an empty cache."""
        result = get_cached_translation(b"dummy pdf content", "bn")
        assert result is None

    def test_cache_hit(self):
        """Should return data after saving."""
        pdf_bytes = b"my paper data"
        lang = "bn"
        save_translation(
            pdf_bytes=pdf_bytes,
            language=lang,
            translated_markdown="# My Paper",
            verification_score=0.98,
            model_used="gemini"
        )
        
        result = get_cached_translation(pdf_bytes, lang)
        assert result is not None
        assert result["translated_markdown"] == "# My Paper"
        assert result["verification_score"] == 0.98

    def test_cache_miss_different_language(self):
        """Should be a miss if the language is different."""
        pdf_bytes = b"my paper data"
        save_translation(
            pdf_bytes=pdf_bytes,
            language="bn",
            translated_markdown="# My Paper",
            verification_score=0.98,
            model_used="gemini"
        )
        
        result = get_cached_translation(pdf_bytes, "hi")
        assert result is None

    def test_low_score_eviction(self):
        """Should ignore cache entries with a score below the minimum threshold."""
        pdf_bytes = b"bad translation"
        lang = "bn"
        save_translation(
            pdf_bytes=pdf_bytes,
            language=lang,
            translated_markdown="# Bad",
            verification_score=0.50, # Low score
            model_used="gemini"
        )
        
        # Requesting with a min_score of 0.80 should return None
        result = get_cached_translation(pdf_bytes, lang, min_score=0.80)
        assert result is None

    def test_flag_invalidation(self):
        """Should ignore cache entries that have been flagged too many times."""
        pdf_bytes = b"flagged translation"
        lang = "bn"
        save_translation(
            pdf_bytes=pdf_bytes,
            language=lang,
            translated_markdown="# Flagged",
            verification_score=0.98,
            model_used="gemini"
        )
        
        hash_key = get_hash(pdf_bytes, lang)
        
        # Flag 3 times
        flag_translation(hash_key, "wrong abstract 1")
        flag_translation(hash_key, "wrong abstract 2")
        flag_translation(hash_key, "wrong abstract 3")
        
        # Should now be a cache miss due to quarantine
        result = get_cached_translation(pdf_bytes, lang)
        assert result is None
