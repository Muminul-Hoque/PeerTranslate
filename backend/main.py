"""
PeerTranslate — FastAPI Application

Main entry point for the backend server. Serves the frontend,
handles PDF uploads, and streams translations via SSE.
"""

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from backend.config import (
    PROJECT_ROOT,
    SUPPORTED_LANGUAGES,
    get_settings,
)
from backend.glossary import get_available_glossaries, load_glossary
from backend.translator import translate_paper
from backend.cache import flag_translation, _get_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# FastAPI Application
# ──────────────────────────────────────────────

app = FastAPI(
    title="PeerTranslate",
    description=(
        "Translate research papers into your own language "
        "with verified accuracy."
    ),
    version="0.1.0",
)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(frontend_dir)),
        name="static",
    )


# ──────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────

class TermContribution(BaseModel):
    language: str
    domain: str
    contributor_name: str
    terms: dict


@app.post("/api/contribute")
async def submit_contribution(data: TermContribution):
    """Save an inline glossary contribution to the pending database."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        
        cursor.execute(
            """
            INSERT INTO community_contributions (language, domain, terms_json, contributor_name)
            VALUES (?, ?, ?, ?)
            """,
            (
                data.language,
                data.domain,
                json.dumps(data.terms, ensure_ascii=False),
                data.contributor_name
            )
        )
        conn.commit()
        return {"status": "success", "message": "Contribution saved to queue."}
    except Exception as e:
        logger.error(f"Failed to save contribution: {e}")
        raise HTTPException(status_code=500, detail="Database insertion failed.")

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = frontend_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Frontend not found. Run from the project root.",
        )
    return HTMLResponse(content=index_path.read_text(encoding="utf-8"))


@app.get("/contribute", response_class=HTMLResponse)
async def serve_contribute():
    """Serve the web glossary contributor page."""
    contribute_path = frontend_dir / "contribute.html"
    if not contribute_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Contribute page not found.",
        )
    return HTMLResponse(content=contribute_path.read_text(encoding="utf-8"))


@app.get("/api/languages")
async def get_languages():
    """Return all supported languages with glossary availability."""
    glossaries = get_available_glossaries()
    languages = []
    for code, name in SUPPORTED_LANGUAGES.items():
        languages.append(
            {
                "code": code,
                "name": name,
                "has_glossary": code in glossaries,
                "glossary_domains": glossaries.get(code, []),
            }
        )
    return JSONResponse(content={"languages": languages})


@app.get("/api/glossary/{lang_code}/{domain}")
async def get_glossary(lang_code: str, domain: str):
    """Return glossary terms for a specific language and domain."""
    terms = load_glossary(lang_code, domain)
    if not terms:
        return JSONResponse(
            content={
                "message": f"No glossary found for {lang_code}/{domain}",
                "terms": {},
            }
        )
    return JSONResponse(
        content={
            "language": lang_code,
            "domain": domain,
            "term_count": len(terms),
            "terms": terms,
        }
    )


from typing import Optional
import httpx

@app.post("/api/translate")
async def translate(
    file: Optional[UploadFile] = None,
    url: Optional[str] = Form(None),
    language: str = Form(default="bn"),
    api_key: Optional[str] = Form(None),
    user_model: Optional[str] = Form(None),
    user_provider: Optional[str] = Form(default="google"),
    judge_provider: Optional[str] = Form(default="google"),
    judge_model: Optional[str] = Form(None),
    judge_api_key: Optional[str] = Form(None),
):
    """
    Accept a PDF upload or a URL, and stream the translation pipeline
    via Server-Sent Events (SSE).
    """
    if not file and not url:
        raise HTTPException(
            status_code=400,
            detail="You must provide either a PDF file upload or a URL.",
        )

    # Validate language
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {language}. "
            f"Supported: {list(SUPPORTED_LANGUAGES.keys())}",
        )

    # Validate API key
    try:
        settings = get_settings()
        settings.validate()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))

    pdf_content = b""
    filename = "unknown.pdf"

    if url:
        if not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Invalid URL format.")
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                pdf_content = response.content
                filename = url.split("/")[-1] or "downloaded.pdf"
        except Exception as e:
            logger.error(f"Failed to download PDF: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download PDF from URL: {str(e)}",
            )
    else:
        # Validate file type
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are accepted.",
            )
        # Read PDF content
        pdf_content = await file.read()
        filename = file.filename

    # Check file size
    max_size = settings.max_file_size_mb * 1024 * 1024
    if len(pdf_content) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {settings.max_file_size_mb}MB",
        )

    # Basic PDF signature check
    if not pdf_content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=400, 
            detail="The downloaded file does not appear to be a valid PDF."
        )

    # Trace parameters for debugging provider selection
    logger.info(
        f"Incoming Request: file={filename}, lang={language}, "
        f"provider={user_provider}, model={user_model}, judge={judge_provider}, "
        f"has_api_key={bool(api_key)}"
    )

    async def event_generator():
        """Generate SSE events from the translation pipeline."""
        try:
            async for event in translate_paper(
                pdf_content, 
                language, 
                settings, 
                api_key, 
                user_model, 
                user_provider,
                judge_provider,
                judge_model,
                judge_api_key
            ):
                yield {
                    "event": event["type"],
                    "data": json.dumps(event["data"])
                }
        except Exception as e:
            logger.error(f"Translation pipeline error: {e}", exc_info=True)
            yield {
                "event": "error",
                "data": f"Translation failed: {str(e)}",
            }

    return EventSourceResponse(event_generator())


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}

class FlagRequest(BaseModel):
    hash_key: str
    reason: str
    language: str
    timestamp: str

@app.post("/api/flag")
async def flag_endpoint(request: FlagRequest):
    """Community flagging endpoint for bad translations."""
    if not request.hash_key:
        raise HTTPException(status_code=400, detail="Missing hash_key")
        
    success = flag_translation(request.hash_key, request.reason)
    if success:
        return {"status": "ok"}
    else:
        raise HTTPException(status_code=404, detail="Translation not found in cache.")


# ──────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
