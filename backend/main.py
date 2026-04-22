"""
PeerTranslate — FastAPI Application

Main entry point for the backend server. Serves the frontend,
handles PDF uploads, and streams translations via SSE.
"""

import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
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

# ── Rate Limiter (in-memory, per-IP) ──
# Max 10 glossary contributions per IP per hour
RATE_LIMIT_WINDOW = 3600  # seconds (1 hour)
RATE_LIMIT_MAX = 10
_rate_limiter: dict[str, list[float]] = defaultdict(list)

def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is within the rate limit, False if exceeded."""
    now = time.time()
    # Prune old timestamps
    _rate_limiter[ip] = [t for t in _rate_limiter[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limiter[ip]) >= RATE_LIMIT_MAX:
        return False
    _rate_limiter[ip].append(now)
    return True

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
    contributor_name: Optional[str] = None
    affiliation: Optional[str] = None
    terms: dict


@app.post("/api/contribute")
async def submit_contribution(data: TermContribution, request: Request):
    """Save an inline glossary contribution to the pending database."""
    
    # ── Rate Limiting ──
    client_ip = request.client.host if request.client else "unknown"
    if not _check_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Maximum 10 contributions per hour."
        )
    
    # ── Input Sanitization ──
    if not data.terms or len(data.terms) == 0:
        raise HTTPException(status_code=400, detail="You must provide at least one term.")
    if len(data.terms) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 terms per submission.")
    
    MAX_TERM_LEN = 200
    sanitized_terms = {}
    for eng, translated in data.terms.items():
        eng_clean = str(eng).strip()[:MAX_TERM_LEN]
        tgt_clean = str(translated).strip()[:MAX_TERM_LEN]
        if eng_clean and tgt_clean:
            sanitized_terms[eng_clean] = tgt_clean
    
    if not sanitized_terms:
        raise HTTPException(status_code=400, detail="All terms were empty after sanitization.")
    
    try:
        conn = _get_db()
        cursor = conn.cursor()
        
        name_to_save = data.contributor_name.strip()[:100] if data.contributor_name else "Anonymous"
        affiliation_to_save = data.affiliation.strip()[:200] if data.affiliation else None
        
        cursor.execute(
            """
            INSERT INTO community_contributions (language, domain, terms_json, contributor_name, contributor_affiliation)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                data.language[:10],
                data.domain[:50],
                json.dumps(sanitized_terms, ensure_ascii=False),
                name_to_save,
                affiliation_to_save
            )
        )
        conn.commit()
        logger.info(f"✅ Contribution saved: {len(sanitized_terms)} terms in {data.language} from {client_ip}")
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
    quick_mode: Optional[str] = Form(None),
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
        
        # ── Auto-normalize common academic URLs to direct PDF links ──
        import re as _re
        
        # arXiv: /abs/2307.03172 → /pdf/2307.03172
        arxiv_abs = _re.match(r'https?://arxiv\.org/abs/(.+?)(?:v\d+)?$', url)
        if arxiv_abs:
            url = f"https://arxiv.org/pdf/{arxiv_abs.group(1)}"
            logger.info(f"Auto-converted arXiv abstract → PDF: {url}")
        
        # bioRxiv / medRxiv: add .full.pdf if not already a PDF link
        biorxiv_match = _re.match(r'(https?://(?:www\.)?(?:biorxiv|medrxiv)\.org/content/.+?)(?:\.full\.pdf)?$', url)
        if biorxiv_match and not url.endswith('.pdf'):
            url = biorxiv_match.group(1) + ".full.pdf"
            logger.info(f"Auto-converted bioRxiv/medRxiv → PDF: {url}")
        
        # PubMed Central: /articles/PMC... → /articles/PMC.../pdf
        pmc_match = _re.match(r'https?://(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/(PMC\d+)/?$', url)
        if pmc_match:
            url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_match.group(1)}/pdf"
            logger.info(f"Auto-converted PMC → PDF: {url}")
        
        # Browser-like headers to avoid 403 from publisher CDNs
        download_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/pdf,*/*",
        }
        
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=download_headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                pdf_content = response.content
                filename = url.split("/")[-1] or "downloaded.pdf"
                
                # Detect if the server returned HTML instead of a PDF
                if "text/html" in content_type and not pdf_content.startswith(b"%PDF"):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "This URL returned an HTML page, not a PDF file. "
                            "Publishers like ScienceDirect, IEEE, and Springer serve article viewer pages at this URL. "
                            "Please use the direct PDF download link instead (usually ending in .pdf), "
                            "or download the PDF to your device and use the 'Upload File' tab."
                        ),
                    )
        except HTTPException:
            raise  # Re-raise our custom errors
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to download PDF: {e}")
            status = e.response.status_code
            if status == 403:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "403 Forbidden — This publisher blocks automated downloads. "
                        "Please download the PDF manually to your device, "
                        "then use the 'Upload File' tab to translate it."
                    ),
                )
            raise HTTPException(
                status_code=400,
                detail=f"Failed to download PDF from URL (HTTP {status}): {str(e)}",
            )
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

    is_quick_mode = quick_mode and quick_mode.lower() == 'true'
    
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
                judge_api_key,
                quick_mode=is_quick_mode
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


@app.get("/api/leaderboard")
async def get_leaderboard():
    """Return top glossary contributors by term count."""
    try:
        import json as _json
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT contributor_name, contributor_affiliation, language,
                   COUNT(*) as submissions,
                   SUM(LENGTH(terms_json) - LENGTH(REPLACE(terms_json, '":', ''))) as approx_terms
            FROM community_contributions
            WHERE status != 'rejected'
            GROUP BY contributor_name, contributor_affiliation, language
            ORDER BY approx_terms DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        contributors = [
            {
                "name": r[0],
                "affiliation": r[1] or "",
                "language": r[2],
                "submissions": r[3],
                "term_count": r[4]
            } for r in rows
        ]
        return JSONResponse(content={"contributors": contributors})
    except Exception as e:
        logger.error(f"Leaderboard error: {e}")
        return JSONResponse(content={"contributors": []})


@app.get("/leaderboard", response_class=HTMLResponse)
async def serve_leaderboard():
    """Serve the contributor leaderboard page."""
    path = frontend_dir / "leaderboard.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Leaderboard page not found.")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))

@app.get("/review", response_class=HTMLResponse)
async def serve_review():
    """Serve the collaborative review page."""
    path = frontend_dir / "review.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Review page not found.")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))

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
# Export Endpoints
# ──────────────────────────────────────────────

class ExportRequest(BaseModel):
    markdown: str
    filename: Optional[str] = "peertranslate_output"

@app.post("/api/export/docx")
async def export_docx(data: ExportRequest):
    """Convert markdown translation to DOCX."""
    from backend.exporter import markdown_to_docx
    from fastapi.responses import Response
    try:
        docx_bytes = markdown_to_docx(data.markdown, title=data.filename)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{data.filename}.docx"'}
        )
    except Exception as e:
        logger.error(f"DOCX export failed: {e}")
        raise HTTPException(status_code=500, detail=f"DOCX export failed: {str(e)}")

@app.post("/api/export/latex")
async def export_latex(data: ExportRequest):
    """Convert markdown translation to LaTeX."""
    from backend.exporter import markdown_to_latex
    from fastapi.responses import Response
    try:
        latex_str = markdown_to_latex(data.markdown)
        return Response(
            content=latex_str.encode("utf-8"),
            media_type="application/x-tex",
            headers={"Content-Disposition": f'attachment; filename="{data.filename}.tex"'}
        )
    except Exception as e:
        logger.error(f"LaTeX export failed: {e}")
        raise HTTPException(status_code=500, detail=f"LaTeX export failed: {str(e)}")


@app.post("/api/export/pdf-preserved")
async def export_pdf_preserved(
    file: UploadFile = File(...),
    translated_markdown: str = Form(...),
    original_english: str = Form(""),
    language: str = Form("bn"),
    filename: str = Form("peertranslate_output"),
):
    """
    Generate a layout-preserved PDF where the original text is replaced
    with translations at the same coordinates, preserving figures and equations.
    """
    from backend.pdf_renderer import render_preserved_pdf
    from fastapi.responses import Response

    pdf_content = await file.read()
    if not pdf_content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Invalid PDF file.")

    try:
        result_bytes = render_preserved_pdf(
            original_pdf_bytes=pdf_content,
            original_english_text=original_english,
            translated_markdown=translated_markdown,
            target_language=language,
        )
        return Response(
            content=result_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}_translated.pdf"'}
        )
    except Exception as e:
        logger.error(f"PDF-preserved export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Layout-preserved PDF export failed: {str(e)}")


# ──────────────────────────────────────────────
# DOI → Open-Access PDF Resolver (Unpaywall)
# ──────────────────────────────────────────────

@app.get("/api/resolve-doi/{doi:path}")
async def resolve_doi(doi: str):
    """Resolve a DOI to an open-access PDF URL via Unpaywall API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": "peertranslate@users.noreply.github.com"}
            )
            if resp.status_code != 200:
                return JSONResponse(content={"pdf_url": None, "error": "DOI not found in Unpaywall."})
            
            data = resp.json()
            best_oa = data.get("best_oa_location") or {}
            pdf_url = best_oa.get("url_for_pdf")
            landing_url = best_oa.get("url_for_landing_page")
            
            if pdf_url:
                return JSONResponse(content={"pdf_url": pdf_url, "source": "unpaywall_oa"})
            elif landing_url:
                return JSONResponse(content={"pdf_url": None, "landing_url": landing_url, "error": "Open-access landing page found but no direct PDF. Try downloading from the landing page."})
            else:
                return JSONResponse(content={"pdf_url": None, "error": "This paper is not available as open-access. Please download the PDF manually."})
    except Exception as e:
        logger.error(f"DOI resolve error: {e}")
        return JSONResponse(content={"pdf_url": None, "error": f"Failed to resolve DOI: {str(e)}"})


# ──────────────────────────────────────────────
# Collaborative Review Endpoint
# ──────────────────────────────────────────────

@app.get("/api/review/pending")
async def get_pending_contributions():
    """Return all pending community contributions for review."""
    try:
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, language, domain, terms_json, contributor_name,
                   contributor_affiliation, status, created_at
            FROM community_contributions
            WHERE status = 'pending'
            ORDER BY created_at DESC
            LIMIT 100
        """)
        rows = cursor.fetchall()
        contributions = [
            {
                "id": r[0], "language": r[1], "domain": r[2],
                "terms": json.loads(r[3]), "contributor": r[4],
                "affiliation": r[5] or "", "status": r[6], "created_at": str(r[7])
            } for r in rows
        ]
        return JSONResponse(content={"contributions": contributions})
    except Exception as e:
        logger.error(f"Review endpoint error: {e}")
        return JSONResponse(content={"contributions": []})

class ReviewAction(BaseModel):
    contribution_id: int
    action: str  # "approve" or "reject"

@app.post("/api/review/action")
async def review_contribution(data: ReviewAction):
    """Approve or reject a pending contribution."""
    if data.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Action must be 'approve' or 'reject'")
    try:
        new_status = "approved" if data.action == "approve" else "rejected"
        conn = _get_db()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE community_contributions SET status = ? WHERE id = ?",
            (new_status, data.contribution_id)
        )
        conn.commit()
        return {"status": "ok", "new_status": new_status}
    except Exception as e:
        logger.error(f"Review action error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update contribution.")


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
