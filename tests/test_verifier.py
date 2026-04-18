"""
Unit tests for the PeerTranslate Verifier module.
"""

import pytest
from backend.verifier import (
    SectionScore,
    VerificationReport,
    compute_similarity,
    split_into_sections,
    check_terminology,
    build_verification_report,
)


class TestSectionScore:
    """Tests for SectionScore dataclass."""

    def test_is_confident_above_threshold(self):
        score = SectionScore("Abstract", "orig", "back", 0.97)
        assert score.is_confident is True

    def test_is_confident_below_threshold(self):
        score = SectionScore("Abstract", "orig", "back", 0.80)
        assert score.is_confident is False

    def test_is_confident_at_boundary(self):
        score = SectionScore("Abstract", "orig", "back", 0.96)
        assert score.is_confident is True

    def test_confidence_label_excellent(self):
        score = SectionScore("Abstract", "orig", "back", 0.99)
        assert score.confidence_label == "excellent"

    def test_confidence_label_good(self):
        score = SectionScore("Abstract", "orig", "back", 0.96)
        assert score.confidence_label == "good"

    def test_confidence_label_needs_review(self):
        score = SectionScore("Abstract", "orig", "back", 0.75)
        assert score.confidence_label == "needs_review"

    def test_confidence_label_low(self):
        score = SectionScore("Abstract", "orig", "back", 0.40)
        assert score.confidence_label == "low_confidence"


class TestComputeSimilarity:
    """Tests for the compute_similarity function."""

    def test_identical_texts(self):
        score = compute_similarity("hello world", "hello world")
        assert score >= 0.99

    def test_completely_different(self):
        score = compute_similarity("hello world", "xyz abc 123")
        assert score < 0.5

    def test_empty_strings(self):
        score = compute_similarity("", "")
        assert isinstance(score, float)

    def test_partial_match(self):
        score = compute_similarity(
            "The attention mechanism is fundamental to transformers.",
            "The attention mechanism is key to transformer models."
        )
        assert 0.5 < score < 1.0


class TestSplitIntoSections:
    """Tests for the split_into_sections function."""

    def test_basic_split(self):
        text = "# Title\nSome content\n## Section 1\nMore content"
        sections = split_into_sections(text)
        assert len(sections) >= 2

    def test_preserves_content(self):
        text = "# Title\nBody text here\n## Abstract\nAbstract content"
        sections = split_into_sections(text)
        titles = [s["title"] for s in sections]
        assert "Abstract" in titles

    def test_deduplication_abstract(self):
        """Duplicate abstracts should be merged/removed."""
        text = "# Title\nBody\n## Abstract\nFirst abstract\n## Abstract\nDuplicate abstract"
        sections = split_into_sections(text)
        abstract_count = sum(1 for s in sections if s["title"].lower() == "abstract")
        assert abstract_count == 1

    def test_deduplication_bengali_abstract(self):
        """Duplicate Bengali abstracts should also be deduplicated."""
        text = "# শিরোনাম\nBody\n## সারসংক্ষেপ\nFirst\n## সারসংক্ষেপ\nDuplicate"
        sections = split_into_sections(text)
        abstract_count = sum(1 for s in sections if s["title"] == "সারসংক্ষেপ")
        assert abstract_count == 1

    def test_empty_text(self):
        sections = split_into_sections("")
        assert isinstance(sections, list)


class TestCheckTerminology:
    """Tests for terminology flagging."""

    def test_correct_terms(self):
        glossary = {"attention mechanism": "অ্যাটেনশন মেকানিজম"}
        text = "অ্যাটেনশন মেকানিজম is used"
        flagged = check_terminology(text, glossary)
        assert len(flagged) == 0

    def test_missing_terms(self):
        glossary = {"attention mechanism": "অ্যাটেনশন মেকানিজম"}
        text = "Some text without the term"
        flagged = check_terminology(text, glossary)
        # Should not flag if term isn't expected to appear
        assert isinstance(flagged, list)


class TestVerificationReport:
    """Tests for the VerificationReport dataclass."""

    def test_overall_score_empty(self):
        report = VerificationReport()
        assert report.overall_score == 0.0

    def test_overall_score_with_sections(self):
        report = VerificationReport(section_scores=[
            SectionScore("A", "", "", 0.90),
            SectionScore("B", "", "", 0.80),
        ])
        assert 0.84 < report.overall_score < 0.86

    def test_flagged_sections(self):
        report = VerificationReport(section_scores=[
            SectionScore("A", "", "", 0.99),
            SectionScore("B", "", "", 0.50),
        ])
        assert len(report.flagged_sections) == 1
