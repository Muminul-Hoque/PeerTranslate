"""
PeerTranslate — Translation Cache Engine

Provides a SQLite-backed cache to prevent duplicate API calls for
identical papers translated into the same language. Features a
community-driven 'Flag & Refresh' system for correcting bad translations.

This engine is WAL-mode enabled, safe for concurrent multi-user access.
SPDX-License-Identifier: GPL-3.0-or-later
"""

import sqlite3
try:
    import libsql_client as libsql
except ImportError:
    libsql = None

import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
from backend.config import get_settings

logger = logging.getLogger(__name__)

CACHE_DB_PATH = Path(__file__).parent.parent / "translation_cache.db"
FLAG_THRESHOLD = 3  # Number of flags before auto-invalidation


def _get_db():
    """Get a database connection (LibSQL for cloud, SQLite for local)."""
    settings = get_settings()
    
    # Use Turso/LibSQL if credentials are provided
    if settings.turso_database_url and libsql:
        logger.info("Connecting to Turso Cloud Database...")
        conn = libsql.connect(
            settings.turso_database_url, 
            auth_token=settings.turso_auth_token
        )
    else:
        # Fallback to local SQLite
        logger.info(f"Connecting to Local SQLite Database: {CACHE_DB_PATH}")
        conn = sqlite3.connect(CACHE_DB_PATH)
        conn.row_factory = sqlite3.Row

    cursor = conn.cursor()

    # Create Translations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS translations (
            hash_key TEXT PRIMARY KEY,
            language TEXT NOT NULL,
            translated_markdown TEXT NOT NULL,
            verification_score REAL NOT NULL,
            model_used TEXT NOT NULL,
            glossary_version TEXT NOT NULL,
            paper_domain TEXT DEFAULT 'general',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            flag_count INTEGER DEFAULT 0
        )
    """)

    # Create Community Contributions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS community_contributions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            language TEXT NOT NULL,
            domain TEXT NOT NULL,
            terms_json TEXT NOT NULL,
            contributor_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_language ON translations(language)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_domain ON translations(paper_domain)")

    # Migration for paper_domain
    try:
        cursor.execute("ALTER TABLE translations ADD COLUMN paper_domain TEXT DEFAULT 'general'")
    except:
        pass

    conn.commit()
    return conn


def _generate_key(content_bytes: bytes, language: str) -> str:
    """Generate a unique SHA-256 hash for a PDF + Target Language."""
    hasher = hashlib.sha256()
    hasher.update(content_bytes)
    hasher.update(language.encode("utf-8"))
    return hasher.hexdigest()


def get_cached_translation(
    pdf_bytes: bytes, language: str, min_score: float = 0.80
) -> Optional[Dict[str, Any]]:
    """
    Look up a cached translation for a given PDF and language.
    Ignores entries that have been flagged too many times or scored too low.
    """
    key = _generate_key(pdf_bytes, language)
    
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM translations WHERE hash_key = ?", (key,)
            )
            row = cursor.fetchone()

            if row:
                data = dict(row)
                if data["flag_count"] >= FLAG_THRESHOLD:
                    logger.warning(f"Cache hit but entry is quarantined (flags >= {FLAG_THRESHOLD}).")
                    return None
                    
                if data["verification_score"] < min_score:
                    logger.warning(f"Cache hit but score ({data['verification_score']}) is below minimum ({min_score}).")
                    return None
                
                logger.info(f"✅ Cache HIT for {language} translation!")
                return data
                
    except Exception as e:
        logger.error(f"Cache read error: {e}")
        
    return None


def save_translation(
    pdf_bytes: bytes,
    language: str,
    translated_markdown: str,
    verification_score: float,
    model_used: str,
    glossary_version: str = "1.0.0",
    paper_domain: str = "general",
) -> None:
    """Store a successful translation in the cache with domain classification."""
    key = _generate_key(pdf_bytes, language)
    
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO translations 
                (hash_key, language, translated_markdown, verification_score,
                 model_used, glossary_version, paper_domain, flag_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                (key, language, translated_markdown, verification_score,
                 model_used, glossary_version, paper_domain)
            )
            logger.info(f"💾 Translation saved to cache for {language} [{paper_domain}].")
    except Exception as e:
        logger.error(f"Cache save error: {e}")


def flag_translation(hash_key: str, reason: str = "") -> bool:
    """Increment the flag count for a bad translation."""
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE translations SET flag_count = flag_count + 1 WHERE hash_key = ?",
                (hash_key,)
            )
            if cursor.rowcount > 0:
                logger.warning(f"🚩 Translation flagged. Reason: {reason}")
                return True
    except Exception as e:
        logger.error(f"Cache flag error: {e}")
    return False

def get_hash(pdf_bytes: bytes, language: str) -> str:
    """Public helper to get a hash key for flagging purposes."""
    return _generate_key(pdf_bytes, language)


def get_domain_stats() -> List[Dict[str, Any]]:
    """
    Return aggregate stats grouped by language + domain.
    Powers the 'Browse by Field' community feature.
    Example return:
        [{"language": "bn", "paper_domain": "ml", "count": 42, "avg_score": 0.97}, ...]
    """
    try:
        with _get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT language, paper_domain,
                       COUNT(*) as count,
                       ROUND(AVG(verification_score), 3) as avg_score
                FROM translations
                WHERE flag_count < ?
                GROUP BY language, paper_domain
                ORDER BY count DESC
                """,
                (FLAG_THRESHOLD,)
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"Stats query error: {e}")
        return []
