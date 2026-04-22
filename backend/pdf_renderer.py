"""
PeerTranslate — Layout-Preserved PDF Renderer

Uses PyMuPDF (fitz) to create translated PDFs that preserve the original
layout, equations, and figures. Replaces only the text blocks with their
translated counterparts, using the correct font for each target language.

SPDX-License-Identifier: CC-BY-NC-4.0
"""

import fitz  # PyMuPDF
import io
import logging
import re
import os
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FONTS_DIR = Path(__file__).parent.parent / "fonts"

# ── Language → Font Mapping ──
# Maps ISO 639-1 codes to Google Noto font filenames.
# Latin-script languages (es, fr, de, pt, tr, sw) use the default NotoSans.
FONT_MAP = {
    "bn": "NotoSansBengali-Regular.ttf",
    "hi": "NotoSansDevanagari-Regular.ttf",
    "ta": "NotoSansTamil-Regular.ttf",
    "ur": "NotoNastaliqUrdu-Regular.ttf",
    "ar": "NotoSansArabic-Regular.ttf",
    "ja": "NotoSansCJKjp-Regular.otf",
    "ko": "NotoSansCJKkr-Regular.otf",
    "zh": "NotoSansCJKsc-Regular.otf",
    "ru": "NotoSans-Regular.ttf",
    "es": "NotoSans-Regular.ttf",
    "fr": "NotoSans-Regular.ttf",
    "de": "NotoSans-Regular.ttf",
    "pt": "NotoSans-Regular.ttf",
    "tr": "NotoSans-Regular.ttf",
    "sw": "NotoSans-Regular.ttf",
}

# Google Fonts CDN base URL for Noto fonts
NOTO_CDN = "https://github.com/google/fonts/raw/main/ofl"

# Direct download URLs for each font file
FONT_URLS = {
    "NotoSansBengali-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/notosansbengali/NotoSansBengali%5Bwdth%2Cwght%5D.ttf",
    "NotoSansDevanagari-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth%2Cwght%5D.ttf",
    "NotoSansTamil-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/notosanstamil/NotoSansTamil%5Bwdth%2Cwght%5D.ttf",
    "NotoNastaliqUrdu-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/notonastaliqurdu/NotoNastaliqUrdu%5Bwght%5D.ttf",
    "NotoSansArabic-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/notosansarabic/NotoSansArabic%5Bwdth%2Cwght%5D.ttf",
    "NotoSans-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/notosans/NotoSans%5Bwdth%2Cwght%5D.ttf",
    # CJK fonts from noto-cjk releases (these are large)
    "NotoSansCJKjp-Regular.otf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/Japanese/NotoSansCJKjp-Regular.otf",
    "NotoSansCJKkr-Regular.otf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/Korean/NotoSansCJKkr-Regular.otf",
    "NotoSansCJKsc-Regular.otf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf",
}

# RTL languages that need right-to-left text insertion
RTL_LANGUAGES = {"ar", "ur"}


def _ensure_font(language_code: str) -> Optional[Path]:
    """
    Ensure the correct Noto font is available locally.
    Downloads from Google Fonts if not present.
    Returns the path to the font file, or None if unavailable.
    """
    font_name = FONT_MAP.get(language_code)
    if not font_name:
        logger.warning(f"No font mapping for language: {language_code}")
        return None

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    font_path = FONTS_DIR / font_name

    if font_path.exists():
        return font_path

    # Download the font
    url = FONT_URLS.get(font_name)
    if not url:
        logger.warning(f"No download URL for font: {font_name}")
        return None

    logger.info(f"Downloading font: {font_name} ...")
    try:
        urllib.request.urlretrieve(url, str(font_path))
        logger.info(f"Font downloaded: {font_path} ({font_path.stat().st_size} bytes)")
        return font_path
    except Exception as e:
        logger.error(f"Failed to download font {font_name}: {e}")
        # Clean up partial download
        if font_path.exists():
            font_path.unlink()
        return None


def _extract_text_blocks(page: fitz.Page) -> List[Dict]:
    """
    Extract text blocks from a page with their bounding boxes and font info.
    Returns a list of dicts with 'bbox', 'text', 'font_size', 'is_bold'.
    """
    blocks = []
    raw_blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]

    for b in raw_blocks:
        if b["type"] != 0:  # Skip image blocks
            continue

        # Aggregate all text from this block
        block_text = ""
        max_size = 0
        is_bold = False

        for line in b["lines"]:
            line_parts = []
            for span in line["spans"]:
                line_parts.append(span["text"])
                max_size = max(max_size, span["size"])
                if "bold" in span["font"].lower():
                    is_bold = True
            block_text += "".join(line_parts) + "\n"

        block_text = block_text.strip()
        if not block_text:
            continue

        blocks.append({
            "bbox": fitz.Rect(b["bbox"]),
            "text": block_text,
            "font_size": max_size,
            "is_bold": is_bold,
        })

    return blocks


def _normalize_text(text: str) -> str:
    """Normalize text for fuzzy matching between extracted PDF text and markdown."""
    t = text.lower().strip()
    # Remove markdown formatting
    t = re.sub(r'^#+\s*', '', t, flags=re.MULTILINE)
    t = re.sub(r'[*_]{1,3}', '', t)
    # Normalize whitespace
    t = " ".join(t.split())
    return t


def _build_translation_map(
    original_text: str,
    translated_text: str,
) -> Dict[str, str]:
    """
    Build a mapping from normalized original paragraphs to translated paragraphs.
    Uses paragraph-level alignment by splitting on double newlines.
    """
    # Split both texts into paragraphs
    orig_paras = [p.strip() for p in re.split(r'\n\s*\n', original_text) if p.strip()]
    trans_paras = [p.strip() for p in re.split(r'\n\s*\n', translated_text) if p.strip()]

    mapping: Dict[str, str] = {}

    # 1:1 alignment by index
    for i, orig_para in enumerate(orig_paras):
        normalized = _normalize_text(orig_para)
        if not normalized or len(normalized) < 5:
            continue
        if i < len(trans_paras):
            mapping[normalized] = trans_paras[i]

    return mapping


def _find_best_match(
    block_text: str,
    translation_map: Dict[str, str],
    used_keys: set,
) -> Optional[str]:
    """
    Find the best matching translation for a given text block.
    Uses substring matching with a preference for longer matches.
    """
    normalized_block = _normalize_text(block_text)
    if not normalized_block or len(normalized_block) < 5:
        return None

    best_match = None
    best_overlap = 0

    for orig_norm, translated in translation_map.items():
        if orig_norm in used_keys:
            continue

        # Check if the block text is a substring of the original or vice versa
        if normalized_block in orig_norm or orig_norm in normalized_block:
            overlap = min(len(normalized_block), len(orig_norm))
            if overlap > best_overlap:
                best_overlap = overlap
                best_match = (orig_norm, translated)

    if best_match and best_overlap > 10:
        used_keys.add(best_match[0])
        return best_match[1]

    return None


def render_preserved_pdf(
    original_pdf_bytes: bytes,
    original_english_text: str,
    translated_markdown: str,
    target_language: str,
) -> bytes:
    """
    Create a layout-preserved PDF by:
    1. Opening the original PDF
    2. Mapping translated text to original text block positions
    3. Redacting original text blocks
    4. Reinserting translated text at the same coordinates
    5. Preserving images, figures, and equations

    Args:
        original_pdf_bytes: The original PDF file bytes.
        original_english_text: The extracted English text (markdown).
        translated_markdown: The translated text (markdown).
        target_language: ISO 639-1 language code.

    Returns:
        The rendered PDF as bytes.
    """
    # Load the font for this language
    font_path = _ensure_font(target_language)

    # Open the original PDF
    doc = fitz.open("pdf", original_pdf_bytes)

    # Determine body font size from the document
    all_sizes = []
    for page in doc:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for b in blocks:
            if b["type"] == 0:
                for line in b["lines"]:
                    for span in line["spans"]:
                        if span["text"].strip():
                            all_sizes.append(round(span["size"], 1))

    body_size = Counter(all_sizes).most_common(1)[0][0] if all_sizes else 10.0

    # Build the translation lookup map
    translation_map = _build_translation_map(original_english_text, translated_markdown)
    logger.info(f"Built translation map with {len(translation_map)} paragraph pairs.")

    is_rtl = target_language in RTL_LANGUAGES

    # Process each page
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_blocks = _extract_text_blocks(page)

        used_keys: set = set()
        redactions = []  # Collect all redactions first, apply at once

        for block in text_blocks:
            # Skip very short text (page numbers, headers, footers)
            if len(block["text"].strip()) < 10:
                continue

            # Skip blocks that look like equations (mostly symbols/numbers)
            alpha_ratio = sum(1 for c in block["text"] if c.isalpha()) / max(len(block["text"]), 1)
            if alpha_ratio < 0.3:
                continue

            # Find the translated text for this block
            translated = _find_best_match(block["text"], translation_map, used_keys)
            if not translated:
                continue

            # Clean up markdown formatting from translated text for PDF insertion
            clean_translated = translated
            clean_translated = re.sub(r'^#+\s*', '', clean_translated, flags=re.MULTILINE)
            clean_translated = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_translated)
            clean_translated = re.sub(r'\*(.*?)\*', r'\1', clean_translated)
            clean_translated = re.sub(r'`(.*?)`', r'\1', clean_translated)

            # Schedule redaction of the original text
            rect = block["bbox"]
            redactions.append({
                "rect": rect,
                "translated": clean_translated,
                "font_size": block["font_size"],
                "is_bold": block["is_bold"],
            })

        # Apply all redactions at once (PyMuPDF requirement)
        for r in redactions:
            page.add_redact_annot(r["rect"], fill=(1, 1, 1))  # White fill

        page.apply_redactions()

        # Now reinsert translated text
        for r in redactions:
            rect = r["rect"]
            text = r["translated"]
            size = min(r["font_size"], rect.height * 0.9)  # Safety cap

            # Shrink font if the text doesn't fit
            # Start at the original size and reduce until it fits
            current_size = size
            min_size = max(5.0, size * 0.5)  # Don't go below 50% of original

            try:
                if font_path and font_path.exists():
                    font = fitz.Font(fontfile=str(font_path))
                    fontname = font.name

                    # Register the font on the page
                    page.insert_font(fontname=fontname, fontfile=str(font_path))

                    # Insert text with auto-fitting
                    rc = page.insert_textbox(
                        rect,
                        text,
                        fontname=fontname,
                        fontfile=str(font_path),
                        fontsize=current_size,
                        align=fitz.TEXT_ALIGN_RIGHT if is_rtl else fitz.TEXT_ALIGN_LEFT,
                    )

                    # If text overflows (rc < 0), try smaller font
                    while rc < 0 and current_size > min_size:
                        current_size -= 0.5
                        # Re-redact (clear previous text)
                        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
                        rc = page.insert_textbox(
                            rect,
                            text,
                            fontname=fontname,
                            fontfile=str(font_path),
                            fontsize=current_size,
                            align=fitz.TEXT_ALIGN_RIGHT if is_rtl else fitz.TEXT_ALIGN_LEFT,
                        )
                else:
                    # Fallback: use built-in Helvetica (Latin only)
                    page.insert_textbox(
                        rect,
                        text,
                        fontname="helv",
                        fontsize=current_size,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
            except Exception as e:
                logger.warning(f"Failed to insert text at {rect} on page {page_num}: {e}")
                # On failure, try basic insertion without custom font
                try:
                    page.insert_textbox(
                        rect,
                        text,
                        fontname="helv",
                        fontsize=current_size,
                        align=fitz.TEXT_ALIGN_LEFT,
                    )
                except Exception:
                    pass

    # Save to bytes
    output = io.BytesIO()
    doc.save(output, garbage=4, deflate=True)
    doc.close()

    result = output.getvalue()
    logger.info(f"Rendered layout-preserved PDF: {len(result)} bytes")
    return result
