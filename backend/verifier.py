"""
PeerTranslate — Back-Translation Verifier

Implements the verification loop that ensures translation accuracy
by back-translating to English and computing similarity scores.
"""

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SectionScore:
    """Verification score for a single section of the paper."""

    section_title: str
    original_text: str
    back_translated_text: str
    similarity_score: float
    flagged_terms: List[str] = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        """Check if the section meets the confidence threshold."""
        return self.similarity_score >= 0.95

    @property
    def confidence_label(self) -> str:
        """Human-readable confidence label."""
        if self.similarity_score >= 0.96:
            return "excellent"
        elif self.similarity_score >= 0.90:
            return "good"
        elif self.similarity_score >= 0.70:
            return "needs_review"
        else:
            return "low_confidence"


@dataclass
class VerificationReport:
    """Complete verification report for a translated paper."""

    section_scores: List[SectionScore] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        """Compute the average similarity score across all sections."""
        if not self.section_scores:
            return 0.0
        return sum(s.similarity_score for s in self.section_scores) / len(
            self.section_scores
        )

    @property
    def overall_label(self) -> str:
        """Human-readable overall confidence."""
        score = self.overall_score
        if score >= 0.95:
            return "excellent"
        elif score >= 0.85:
            return "good"
        elif score >= 0.70:
            return "needs_review"
        else:
            return "low_confidence"

    @property
    def flagged_sections(self) -> List[SectionScore]:
        """Return sections that need re-translation."""
        return [s for s in self.section_scores if not s.is_confident]

    def to_dict(self) -> Dict:
        """Serialize the report for the frontend."""
        return {
            "overall_score": round(self.overall_score * 100, 1),
            "overall_label": self.overall_label,
            "total_sections": len(self.section_scores),
            "flagged_sections": len(self.flagged_sections),
            "sections": [
                {
                    "title": s.section_title,
                    "score": round(s.similarity_score * 100, 1),
                    "label": s.confidence_label,
                    "flagged_terms": s.flagged_terms,
                }
                for s in self.section_scores
            ],
        }


import re

def compute_similarity(text_a: str, text_b: str) -> float:
    """
    Compute semantic similarity between two texts using
    SequenceMatcher after stripping Markdown formatting.
    """
    if not text_a or not text_b:
        return 0.0

    def clean(text):
        # 1. Lowercase
        t = text.lower()
        # 2. Remove Markdown Headers (e.g. #, ##)
        t = re.sub(r'^#+\s*', '', t, flags=re.MULTILINE)
        # 3. Remove Markdown Bold/Italic (e.g. **, *)
        t = re.sub(r'[*_]{1,3}', '', t)
        # 4. Remove Markdown Lists (e.g. *, -)
        t = re.sub(r'^[*+-]\s*', '', t, flags=re.MULTILINE)
        # 5. Remove Markdown Code (e.g. `)
        t = re.sub(r'`', '', t)
        # 6. Normalize whitespace
        return " ".join(t.split())

    normalized_a = clean(text_a)
    normalized_b = clean(text_b)

    # If both are empty after cleaning (e.g. only symbols), check total equality
    if not normalized_a and not normalized_b:
        return 1.0 if text_a.strip() == text_b.strip() else 0.0

    return SequenceMatcher(None, normalized_a, normalized_b).ratio()


def check_terminology(
    translated_text: str,
    glossary_terms: Dict[str, str],
) -> List[str]:
    """
    Check which glossary terms were NOT properly used in the translation.

    Args:
        translated_text: The translated text to check.
        glossary_terms: Dictionary of English → target language term mappings.

    Returns:
        List of English terms whose translations were NOT found.
    """
    flagged: List[str] = []
    text_lower = translated_text.lower()

    for english_term, target_term in glossary_terms.items():
        if target_term.lower() not in text_lower:
            flagged.append(english_term)

    return flagged


def split_into_sections(text: str) -> List[Dict[str, str]]:
    """
    Split a Markdown document into titled sections.

    Args:
        text: Markdown-formatted text.

    Returns:
        List of dicts with 'title' and 'content' keys.
    """
    sections: List[Dict[str, str]] = []
    current_title = "Introduction"
    current_content: List[str] = []

    seen_titles = set()
    for line in text.split("\n"):
        stripped = line.strip()
        # Only split on H1 and H2. H3s (like bolded table cells) remain inside the section block.
        if stripped.startswith("# ") or stripped.startswith("## "):
            title = stripped.lstrip("#").strip()
            
            # Normalize title for robust deduplication (strip numbers like "1.", "1 ", "1.1")
            normalized_title = title.lower()
            import re
            normalized_title = re.sub(r'^[\d\.\s]+', '', normalized_title).strip()
            
            # De-duplication check: Skip if we've already seen this normalized title
            # and it's a generic section title that usually implies redundancy from metadata vs body.
            generic_sections = {"abstract", "সারসংক্ষেপ", "introduction", "ভূমিকা", "conclusion", "उपसंहार", "परिचय", "सार"}
            if normalized_title in seen_titles and normalized_title in generic_sections:
                continue
            
            # Save previous section
            # Always emit — even if content is empty, the HEADING itself needs translating
            # (e.g., "3 Method" appears before "3.1 Dataset" with no body text in between)
            content_text = "\n".join(current_content).strip()
            # Only skip if the content is literally just the title repeated
            if content_text.lower() == current_title.lower():
                content_text = ""
            sections.append(
                {
                    "title": current_title,
                    "content": content_text,
                }
            )
            
            current_title = title
            seen_titles.add(normalized_title)
            current_content = []
            
            # Stop if we hit References/Bibliography (optional: keep but don't translate further?)
            # Actually, standard behavior is to include references, but we want to stop fabrication.
        else:
            current_content.append(line)

    # Save the last section
    if current_content:
        sections.append(
            {
                "title": current_title,
                "content": "\n".join(current_content).strip(),
            }
        )

    # ---------------------------------------------------------
    # SAFETY CHUNKER
    # ---------------------------------------------------------
    # Prevent massive LLM payloads by splitting any section > 1000 chars.
    # Paragraph-level chunks (~1000 chars ~ 200 words) for maximum accuracy and speed.
    safe_sections = []
    MAX_CHARS = 1000
    
    for sec in sections:
        content_len = len(sec["content"])
        if content_len <= MAX_CHARS:
            safe_sections.append(sec)
        else:
            logger.info(f"Section '{sec['title']}' is too large ({content_len} chars). Splitting into chunks.")
            paragraphs = sec["content"].split("\n\n")
            current_chunk = []
            current_length = 0
            part_index = 1
            
            for p in paragraphs:
                stripped_p = p.strip()
                if not stripped_p:
                    continue
                
                # If a single paragraph is STILL larger than MAX_CHARS, force-split it
                sub_paragraphs = []
                if len(stripped_p) > MAX_CHARS:
                    # Try splitting by sentence endings
                    sentences = re.split(r'(?<=[.!?])\s+', stripped_p)
                    temp_p = ""
                    for s in sentences:
                        if len(s) > MAX_CHARS:
                            # Still too big! Force split by space
                            words = s.split()
                            for w in words:
                                if len(temp_p) + len(w) > MAX_CHARS and temp_p:
                                    sub_paragraphs.append(temp_p.strip())
                                    temp_p = w + " "
                                else:
                                    temp_p += w + " "
                        elif len(temp_p) + len(s) > MAX_CHARS and temp_p:
                            sub_paragraphs.append(temp_p.strip())
                            temp_p = s + " "
                        else:
                            temp_p += s + " "
                    if temp_p:
                        sub_paragraphs.append(temp_p.strip())
                else:
                    sub_paragraphs = [stripped_p]
                
                for sp in sub_paragraphs:
                    # If adding this sub-paragraph pushes us over the limit, flush the current chunk
                    if current_length + len(sp) > MAX_CHARS and current_chunk:
                        safe_sections.append({
                            "title": sec["title"],
                            "content": "\n\n".join(current_chunk),
                            "_chunk_index": part_index,
                        })
                        part_index += 1
                        current_chunk = []
                        current_length = 0
                    
                    current_chunk.append(sp)
                    current_length += len(sp)
                
            # Append remaining chunk
            if current_chunk:
                safe_sections.append({
                    "title": sec["title"],
                    "content": "\n\n".join(current_chunk),
                    "_chunk_index": part_index if part_index > 1 else None,
                })

    return safe_sections


def build_verification_report(
    original_sections: List[Dict[str, str]],
    back_translated_sections: List[Dict[str, str]],
    translated_text: str,
    glossary_terms: Dict[str, str],
) -> VerificationReport:
    """
    Build a complete verification report by comparing original and
    back-translated sections.

    Args:
        original_sections: Sections extracted from the original text.
        back_translated_sections: Sections from the back-translated text.
        translated_text: The full translated text for terminology checking.
        glossary_terms: Glossary terms to verify.

    Returns:
        A VerificationReport with per-section scores.
    """
    report = VerificationReport()

    # Check terminology across the full translated text
    flagged_terms = check_terminology(translated_text, glossary_terms)

    # Match sections by index and compute scores
    max_sections = min(len(original_sections), len(back_translated_sections))

    for i in range(max_sections):
        orig = original_sections[i]
        back = back_translated_sections[i]

        score = compute_similarity(orig["content"], back["content"])

        section_score = SectionScore(
            section_title=orig["title"],
            original_text=orig["content"][:200],
            back_translated_text=back["content"][:200],
            similarity_score=score,
            flagged_terms=flagged_terms if i == 0 else [],
        )
        report.section_scores.append(section_score)

    logger.info(
        f"Verification complete: overall={report.overall_score:.2f}, "
        f"flagged={len(report.flagged_sections)}/{len(report.section_scores)}"
    )

    return report
