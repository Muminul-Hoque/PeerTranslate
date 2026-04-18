"""
Unit tests for the PeerTranslate Glossary module.
"""

import pytest
from pathlib import Path
from backend.glossary import (
    load_glossary,
    load_all_glossaries,
    build_glossary_prompt,
    get_available_glossaries,
)


class TestLoadGlossary:
    """Tests for glossary file loading."""

    def test_load_bengali_ml_glossary(self):
        terms = load_glossary("bn", "ml")
        assert isinstance(terms, dict)
        assert len(terms) > 0
        assert "attention mechanism" in terms

    def test_load_bengali_cs_glossary(self):
        terms = load_glossary("bn", "cs")
        assert isinstance(terms, dict)
        assert len(terms) > 0

    def test_load_bengali_academic_glossary(self):
        terms = load_glossary("bn", "general_academic")
        assert isinstance(terms, dict)
        assert "abstract" in terms
        assert terms["abstract"] == "সারসংক্ষেপ"

    def test_load_nonexistent_language(self):
        terms = load_glossary("xx", "ml")
        assert terms == {}

    def test_load_nonexistent_domain(self):
        terms = load_glossary("bn", "nonexistent")
        assert terms == {}


class TestLoadAllGlossaries:
    """Tests for merged glossary loading."""

    def test_merge_all_bengali(self):
        merged = load_all_glossaries("bn")
        assert isinstance(merged, dict)
        # Should have terms from all 3 domains
        assert len(merged) >= 50
        # ML term
        assert "attention mechanism" in merged
        # Academic term
        assert "abstract" in merged

    def test_nonexistent_language_returns_empty(self):
        merged = load_all_glossaries("xx")
        assert merged == {}


class TestBuildGlossaryPrompt:
    """Tests for prompt generation."""

    def test_empty_terms(self):
        prompt = build_glossary_prompt({})
        assert prompt == ""

    def test_generates_prompt(self):
        terms = {"attention": "অ্যাটেনশন", "gradient": "গ্রেডিয়েন্ট"}
        prompt = build_glossary_prompt(terms)
        assert "MANDATORY TERMINOLOGY" in prompt
        assert "attention" in prompt
        assert "অ্যাটেনশন" in prompt

    def test_all_terms_included(self):
        terms = load_all_glossaries("bn")
        prompt = build_glossary_prompt(terms)
        for english_term in terms:
            assert english_term in prompt


class TestGetAvailableGlossaries:
    """Tests for glossary discovery."""

    def test_discovers_bengali(self):
        available = get_available_glossaries()
        assert "bn" in available
        assert "ml" in available["bn"]
        assert "cs" in available["bn"]
        assert "general_academic" in available["bn"]
