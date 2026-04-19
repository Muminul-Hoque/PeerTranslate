"""
PeerTranslate — Glossary Module

Loads and manages community-curated academic glossaries for
domain-specific term preservation during translation.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from backend.config import PROJECT_ROOT, SUPPORTED_DOMAINS

logger = logging.getLogger(__name__)

GLOSSARY_DIR = PROJECT_ROOT / "glossaries"


def load_glossary(language_code: str, domain: str) -> Dict[str, str]:
    """
    Load a glossary JSON file for a specific language and domain.

    Args:
        language_code: ISO 639-1 language code (e.g., 'bn' for Bengali).
        domain: Academic domain (e.g., 'ml', 'cs', 'general_academic').

    Returns:
        Dictionary mapping English terms to their translated equivalents.
    """
    glossary_path = GLOSSARY_DIR / language_code / f"{domain}.json"

    if not glossary_path.exists():
        logger.warning(
            f"Glossary not found: {glossary_path}. "
            f"Translation will proceed without domain-specific terms."
        )
        return {}

    try:
        with open(glossary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        terms = data.get("terms", {})
        logger.info(
            f"Loaded {len(terms)} terms from glossary: "
            f"{language_code}/{domain}"
        )
        return terms
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse glossary {glossary_path}: {e}")
        return {}


def load_all_glossaries(language_code: str) -> Dict[str, str]:
    """
    Load and merge all available glossaries for a language.

    Args:
        language_code: ISO 639-1 language code.

    Returns:
        Merged dictionary of all domain terms for the language.
    """
    merged: Dict[str, str] = {}

    for domain in SUPPORTED_DOMAINS:
        terms = load_glossary(language_code, domain)
        merged.update(terms)

    logger.info(
        f"Total glossary terms for '{language_code}': {len(merged)}"
    )
    return merged


def build_glossary_prompt(terms: Dict[str, str]) -> str:
    """
    Build a prompt instruction string that locks glossary terms
    during translation.

    Args:
        terms: Dictionary of English → translated term mappings.

    Returns:
        Formatted instruction string for the LLM prompt.
    """
    if not terms:
        return ""

    lines = [
        "\n## MANDATORY TERMINOLOGY — USE THESE EXACT TRANSLATIONS:",
        "The following academic terms MUST be translated exactly as shown below.",
        "Do NOT paraphrase or alter these terms:\n",
    ]

    for english, translated in terms.items():
        lines.append(f"- \"{english}\" → \"{translated}\"")

    lines.append(
        "\nIf you encounter any of these terms in the source text, "
        "you MUST use the exact translation provided above. "
        "HOWEVER, if the provided translation includes the English term in parentheses (e.g. 'শব্দ (word)'), "
        "ONLY include the parentheses on the FIRST occurrence in your translation to introduce the term. "
        "For all subsequent uses, drop the parentheses and use ONLY the translated portion."
    )

    return "\n".join(lines)


def get_available_glossaries() -> Dict[str, List[str]]:
    """
    Scan the glossary directory and return available language/domain pairs.

    Returns:
        Dictionary mapping language codes to lists of available domains.
    """
    available: Dict[str, List[str]] = {}

    if not GLOSSARY_DIR.exists():
        return available

    for lang_dir in GLOSSARY_DIR.iterdir():
        if lang_dir.is_dir() and lang_dir.name != "__pycache__":
            domains = []
            for json_file in lang_dir.glob("*.json"):
                domains.append(json_file.stem)
            if domains:
                available[lang_dir.name] = sorted(domains)

    return available
