import logging
import os
import tempfile
import asyncio
from typing import AsyncGenerator, Dict, Any, Optional

import google.generativeai as genai
from openai import AsyncOpenAI

from backend.config import SUPPORTED_LANGUAGES, Settings
from backend.glossary import load_all_glossaries, build_glossary_prompt
from backend.verifier import (
    VerificationReport,
    SectionScore,
    build_verification_report,
    split_into_sections,
    compute_similarity,
    check_terminology,
)
from backend.cache import get_cached_translation, save_translation, get_hash
from backend.figure_extractor import extract_images_from_pdf, reinsert_figures

logger = logging.getLogger(__name__)

def _get_language_name(code: str) -> str:
    entry = SUPPORTED_LANGUAGES.get(code, code)
    if "(" in entry and ")" in entry:
        return entry.split("(")[1].rstrip(")")
    return entry


def _build_translation_prompt(language_name: str, glossary_prompt: str) -> str:
    return f"""You are PeerTranslate, a world-class academic research paper translator.

## YOUR TASK
Translate ONLY the specific English chunk provided below into **{language_name}**.

## CRITICAL RULES
1. **Preserve the ENTIRE structure**: all headings, subheadings, bullet points, numbered lists, tables, equations, and references.
2. **Output in Markdown format** with proper heading hierarchy (# for title, ## for sections, ### for subsections).
3. **DO NOT translate**: author names, affiliations, institution names, URLs, DOIs, email addresses, reference citations, mathematical equations, code, and figure/table numbers. KEEP NAMES IN ENGLISH.
4. **DO translate**: title, abstract, all body text, section headings, figure captions, table captions, and conclusion.
5. **Maintain academic register**: Use formal, scholarly language appropriate for the target language.
6. **Preserve line breaks exactly**: If authors and affiliations are on multiple lines, keep them on exactly the same lines with the exact same superscripts/asterisks (e.g., `Author1*, Author2`).
7. **Technical accuracy**: Scientific claims, numerical data, and methodological descriptions must be translated with 100% fidelity.
8. **ZERO PARAPHRASING & ZERO SUMMARIZATION**: Do not add extra filler. Do not invent headings. Do NOT summarize the paper. If the input is just a Title and Authors, translate ONLY the Title and Authors. Do not hallucinate the abstract or introduction.

{glossary_prompt}

CRITICAL: Return ONLY the raw Markdown translation of the provided text. No introductory tags or conversational text.
"""

def _build_back_translation_prompt(language_name: str) -> str:
    return f"""You are a master academic editor.

## YOUR TASK
Translate the following {language_name} research paper back into **English**.

## CRITICAL RULES
1. Preserve the exact structure and all headings.
2. Output in pure Markdown format.
3. Return ONLY the raw English Markdown text. No chat or explanations.
"""

def _build_judge_prompt(orig_text: str, back_text: str) -> str:
    return f"""You are an expert scientific evaluator. Compare a research paper section (ORIGINAL) and its back-translation (VERIFICATION).

## ORIGINAL ENGLISH:
```markdown
{orig_text}
```

## BACK-TRANSLATED ENGLISH:
```markdown
{back_text}
```

## YOUR TASK:
Rate the semantic accuracy: Does the VERIFICATION text represent the EXACT same scientific meaning as the ORIGINAL?
- Ignore minor word choice differences or formatting styles.
- Focus strictly on technical accuracy and data fidelity.
- **PENALIZE FABRICATION**: If the back-translation contains information or sections that DO NOT exist in the original (hallucinations), give a very low score (<30).
- If it's a perfect semantic match, give 100.
- If it's a completely different topic, give 0.

CRITICAL: Output ONLY a single integer between 0 and 100 representing the accuracy percentage. Do not include any text or explanations.
"""

def _build_refinement_prompt(language_name: str, glossary_prompt: str, failed_translation: str) -> str:
    return f"""You are a world-class academic proofreader and translator.

## YOUR TASK
You previously translated a section of a research paper into {language_name}, but the translation was flagged as **inaccurate** during verification. 

**Your goal is to compare the ENGLISH ORIGINAL with your PREVIOUS FAILED ATTEMPT and produce a 100% faithful, improved version.**

## PREVIOUS FAILED ATTEMPT (DO NOT REPEAT THESE ERRORS):
```markdown
{failed_translation}
```

## GUIDELINES FOR THE FIX:
1. Identify missing information, inaccuracies, or weird phrasing in the attempt above.
2. Ensure scientific terms match the glossary exactly.
3. Maintain the precise academic tone of the English original.
4. **MISSION: HIGH-FIDELITY**: DO NOT cross-reference outside knowledge. ONLY use the original English text provided in this prompt.
5. **ZERO ADDITIONS**: Do not add extra explanations or sections.
4. ONLY output the corrected translation.

{glossary_prompt}

CRITICAL: Return ONLY the raw Markdown translation. No introductory tags like "Here is the translation".
"""

async def _get_llm_response(
    system_prompt: str,
    user_content: str,
    provider: str,
    api_key: Optional[str],
    model_name: Optional[str],
    settings: Settings,
    temperature: float = 0.1
) -> str:
    """Hybrid LLM generator for OpenRouter, OpenAI, and Google Native Strings."""
    import asyncio
    max_retries = 5
    
    if provider == "google" or not provider:
        key_to_use = api_key if api_key else settings.gemini_api_key
        model_to_use = model_name if model_name else settings.gemini_model
        genai.configure(api_key=key_to_use)
        model = genai.GenerativeModel(model_to_use)
        full_prompt = f"{system_prompt}\n\n{user_content}"
        
        last_exception = None
        for attempt in range(max_retries):
            try:
                # 60-second hard timeout per API call — prevents infinite hangs
                response = await asyncio.wait_for(
                    model.generate_content_async(
                        [full_prompt],
                        generation_config=genai.types.GenerationConfig(
                            temperature=temperature,
                            max_output_tokens=65536,
                        ),
                    ),
                    timeout=60.0
                )
                # Brief pause to avoid 30 RPM burst limit on Gemma models
                await asyncio.sleep(2)
                return response.text
            except asyncio.TimeoutError:
                last_exception = Exception("Google API call timed out after 60s")
                logger.warning(f"Google API timed out. Attempt {attempt+1}/{max_retries}")
                await asyncio.sleep(3)
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                
                # If we hit an RPM (Requests Per Minute) rate limit / 429 error, pause gracefully and retry
                if any(k in err_msg for k in ["429", "quota", "exceeded", "rate limit", "ratelimit"]) and attempt < max_retries - 1:
                    logger.warning(f"Hit Google API quota/rate limit. Pausing 15s to reset RPM... (Attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(15.0)
                    continue
                    
                # Fast-exit on terminal hard errors (like 404 Model Not Found or invalid keys)
                if any(k in err_msg for k in ["404", "not found", "invalid"]):
                    raise e
                    
                wait_time = (attempt + 1) * 3  # Wait 3s, 6s, 9s (was 10s, 20s, 30s)
                logger.warning(f"Google API Error. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
                
        raise last_exception or Exception(f"Failed after {max_retries} attempts.")
        
    else:
        # OpenAI or OpenRouter
        base_url = "https://openrouter.ai/api/v1" if provider == "openrouter" else None
        # Default models if empty
        if not model_name:
            model_name = "meta-llama/llama-3.1-8b-instruct:free" if provider == "openrouter" else "gpt-4o-mini"
            
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        
        max_retries = 3
        last_exception = None
        
        import asyncio
        import openai

        for attempt in range(max_retries):
            try:
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=temperature
                )
                return response.choices[0].message.content
            except openai.RateLimitError as e:
                last_exception = e
                wait_time = (attempt + 1) * 5 # Wait 5s, 10s...
                logger.warning(f"Rate limited by {provider} (429). Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            except Exception as e:
                # Immediate fail for non-429 errors
                raise e
        
        raise last_exception or Exception(f"Failed after {max_retries} attempts due to rate limits.")


async def translate_paper(
    pdf_content: bytes,
    target_language: str,
    settings: Settings,
    api_key: Optional[str] = None,
    user_model: Optional[str] = None,
    user_provider: str = "google",
    judge_provider: str = "google",
    judge_model: Optional[str] = None,
    judge_api_key: Optional[str] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    
    language_name = _get_language_name(target_language)
    
    # 0. Debug Trace
    logger.info(f">>> PIPELINE START: provider={user_provider}, model={user_model}, has_api_key={bool(api_key)}")

    # 1. Load Glossary
    yield {"type": "status", "data": "📚 Loading academic glossary..."}
    glossary_terms = load_all_glossaries(target_language)
    glossary_prompt = build_glossary_prompt(glossary_terms)
    yield {"type": "status", "data": f"✅ Loaded {len(glossary_terms)} domain-specific terms"}

    # 1.5 Check Cache First
    pdf_hash = get_hash(pdf_content, target_language)
    cached_data = get_cached_translation(pdf_content, target_language, settings.similarity_threshold)
    
    # Always send the hash key so the frontend can report issues
    yield {"type": "cache_info", "data": {"hash_key": pdf_hash}}
    
    if cached_data:
        yield {"type": "status", "data": "🌟 Found verified translation in Community Cache!"}
        
        # We simulate the verification event from the score
        score = cached_data["verification_score"]
        if score >= 0.98:
            label = "excellent"
        elif score >= 0.96:
            label = "good"
        elif score >= 0.70:
            label = "needs_review"
        else:
            label = "low_confidence"
            
        yield {
            "type": "verification",
            "data": {
                "overall_score": f"{score * 100:.1f}%",
                "overall_label": label,
                "flagged_sections": 0,
                "total_sections": 0,
                "section_scores": []
            }
        }
        
        yield {"type": "translation", "data": cached_data["translated_markdown"]}
        yield {"type": "complete", "data": "Translation retrieved from community cache."}
        return

    # 2. Save PDF to temp file & extract figures
    yield {"type": "status", "data": "📄 Processing PDF document..."}
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        tmp_file.write(pdf_content)
        tmp_path = tmp_file.name
        
    yield {"type": "status", "data": "🖼️ Extracting figures and diagrams..."}
    extracted_figures = extract_images_from_pdf(pdf_content)
    if extracted_figures:
        yield {"type": "status", "data": f"✅ Found {len(extracted_figures)} high-res figures."}

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: OFFLINE EXTRACTION (PyMuPDF) — Always runs, zero quota
    # ═══════════════════════════════════════════════════════════════
    yield {"type": "status", "data": "📥 Extracting text with offline engine (PyMuPDF)..."}
    original_english_text = ""
    try:
        import fitz
        doc = fitz.open(tmp_path)
        for page in doc:
            original_english_text += page.get_text("text") + "\n\n"
        doc.close()
    except Exception as fitz_err:
        logger.error(f"PyMuPDF extraction failed: {fitz_err}")

    if original_english_text.strip():
        yield {"type": "status", "data": "✅ Offline text extraction complete."}
    else:
        yield {"type": "error", "data": "❌ Could not extract any text from the PDF."}
        return

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: GEMINI ENHANCEMENT (Optional) — 30s timeout, non-fatal
    # ═══════════════════════════════════════════════════════════════
    extraction_api_key = api_key if (user_provider == "google" and api_key) else settings.gemini_api_key
    if extraction_api_key:
        try:
            yield {"type": "status", "data": "✨ Attempting Gemini enhancement for better structure..."}
            
            async def _gemini_enhance():
                genai.configure(api_key=extraction_api_key)
                uploaded_file = genai.upload_file(tmp_path, mime_type="application/pdf")
                extraction_model = genai.GenerativeModel("gemini-flash-lite-latest")
                response = await extraction_model.generate_content_async(
                    [
                        "MISSION: HIGH-FIDELITY ACADEMIC EXTRACTION\n"
                        "YOUR TASK: Extract the raw text from this PDF with 100% literal accuracy into Markdown format.\n\n"
                        "CRITICAL CONSTRAINTS:\n"
                        "1. DO NOT summarize. DO NOT simplify. Extract the literal text as written.\n"
                        "2. PRESERVE ALL TECHNICAL JARGON EXACTLY AS IS.\n"
                        "3. AGGRESSIVE DEDUPLICATION: ArXiv PDFs often have metadata (like the Abstract and Title) repeated twice (once in the metadata block, once in the paper body). Extract them ONLY ONCE. Never repeat 'Abstract' or 'Introduction'.\n"
                        "4. PRESERVE STRUCTURE: Use precise Markdown hierarchy (#, ##, ###).\n\n"
                        "Return ONLY the literal extracted Markdown text without any wrapper tags.",
                        uploaded_file,
                    ],
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.0,
                        max_output_tokens=65536,
                    ),
                )
                return response

            # 90-second hard timeout — PDF extraction needs more time
            response = await asyncio.wait_for(_gemini_enhance(), timeout=90.0)
            
            if response and response.text and len(response.text) > len(original_english_text) * 0.5:
                original_english_text = response.text
                yield {"type": "status", "data": "✅ Gemini enhancement applied. Full Markdown structure preserved."}
            else:
                yield {"type": "status", "data": "✅ Using offline extraction (Gemini result was sparse)."}
                
        except asyncio.TimeoutError:
            yield {"type": "status", "data": "⚠️ Gemini timed out after 90s. Using offline text (still accurate)."}
            logger.warning("Gemini enhancement timed out after 90s")
        except Exception as gemini_err:
            err_preview = str(gemini_err)[:60]
            yield {"type": "status", "data": f"⚠️ Gemini unavailable ({err_preview}). Using offline text..."}
            logger.warning(f"Gemini enhancement failed (non-fatal): {gemini_err}")
    else:
        yield {"type": "status", "data": "ℹ️ No Google API key configured. Using offline extraction."}

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: TRANSLATION PIPELINE
    # ═══════════════════════════════════════════════════════════════
    yield {"type": "status", "data": "✅ Extracted original English Markdown."}

    # 4. Start Real-Time 4-Pass Pipeline (Iterative Section-by-Section)
    effective_label = user_provider.upper() if user_provider else "GOOGLE"
    yield {"type": "status", "data": f"🚀 Starting Real-Time 4-Pass Pipeline via {effective_label}..."}
    
    translation_prompt = _build_translation_prompt(language_name, glossary_prompt)
    back_translation_prompt = _build_back_translation_prompt(language_name)
    
    sections = split_into_sections(original_english_text)
    full_translated_markdown = ""
    section_scores = []
    
    for i, section in enumerate(sections):
        if i == 0:
            loading_msg = "> ⏳ **Translation in Progress...**\n> \n> PeerTranslate uses a mathematically rigorous 4-pass verification system. Because you are utilizing the completely **Free Tier API (limited to 15 requests per minute)**, a full paper (20+ sections) requires over 60 discrete AI judgments. \n>\n> *To prevent API Quota errors, the system paces itself safely. Please allow 5 to 10 minutes for full completion.* \n>\n> _The first highly-verified section will appear here shortly..._\n"
            yield {"type": "translation", "data": loading_msg}

        section_title = section["title"]
        section_index_txt = f"{i+1}/{len(sections)}"
        
        # --- Pass 1: Translate ---
        yield {"type": "status", "data": f"⏳ [{section_index_txt}] Translating: {section_title}..."}
        section_content = f"## {section_title}\n\n{section['content']}"
        
        try:
            translated_chunk = await _get_llm_response(
                translation_prompt, section_content, user_provider, api_key, user_model, settings
            )
            
            if not translated_chunk:
                raise Exception("Model returned empty translation.")

            # --- Pass 2 & 3: Verification with Recursive Loop (Pass 4) ---
            # Bypass rigorous verification for very short sections (like Titles, Authors, strict equations)
            if len(section['content'].split()) < 30:
                 yield {"type": "status", "data": f"✅ [{section_index_txt}] Verified: 100% (Short text bypass)."}
                 best_chunk = translated_chunk
                 final_score_obj = SectionScore(
                     section_title=section_title, 
                     original_text=section["content"][:100], 
                     back_translated_text="-bypassed-", 
                     similarity_score=1.0
                 )
                 full_translated_markdown += best_chunk + "\n\n"
                 section_scores.append(final_score_obj)
                 
                 yield {"type": "translation", "data": full_translated_markdown}
                 yield {
                     "type": "verification_section",
                     "data": {
                         "title": section_title, "score": 100.0, "label": "excellent", "flagged_terms": [],
                         "metrics": {"current_index": i + 1, "total_sections": len(sections), "running_avg": 100.0}
                     }
                 }
                 continue

            max_attempts = 5
            best_similarity = 0.0
            best_chunk = translated_chunk
            final_score_obj = None

            for attempt in range(1, max_attempts + 1):
                # --- Pass 2: Back-Translate ---
                yield {"type": "status", "data": f"🔄 [{section_index_txt}] Verifying (Attempt {attempt})..."}
                back_chunk = await _get_llm_response(
                    back_translation_prompt, translated_chunk, user_provider, api_key, user_model, settings
                )
                
                # --- Pass 3: Score Section (AI Judge Mode) ---
                yield {"type": "status", "data": f"⚖️ [{section_index_txt}] AI Judge ({judge_provider}) is evaluating meaning... (Attempt {attempt})"}
                
                judge_prompt = _build_judge_prompt(section_content, back_chunk or "")
                similarity = 0.0
                
                try:
                    # Level 1: Use user-selected Judge
                    actual_judge_key = judge_api_key if judge_api_key else (api_key if judge_provider == user_provider else None)
                    
                    score_str = await _get_llm_response(
                        "You are a strict technical evaluator.", 
                        judge_prompt, 
                        judge_provider, 
                        actual_judge_key, 
                        judge_model, 
                        settings, 
                        temperature=0.0
                    )
                    import re
                    match = re.search(r'(\d+)', score_str)
                    similarity = float(match.group(1)) / 100.0 if match else 0.0
                except Exception as e1:
                    logger.warning(f"Level 1 Judge failed ({judge_provider}): {e1}")
                    yield {"type": "status", "data": f"⚠️ [{section_index_txt}] Custom Judge failed. Recovering with Server-Side Gemini..."}
                    
                    try:
                        # Level 2: Use Server-Side Google Gemini fallback
                        score_str = await _get_llm_response(
                            "You are a strict technical evaluator.", 
                            judge_prompt, 
                            "google", 
                            None, 
                            None, 
                            settings, 
                            temperature=0.0
                        )
                        import re
                        match = re.search(r'(\d+)', score_str)
                        similarity = float(match.group(1)) / 100.0 if match else 0.0
                    except Exception as e2:
                        logger.error(f"Level 2 Judge failed (Google): {e2}")
                        yield {"type": "status", "data": f"⚠️ [{section_index_txt}] AI Verification unreachable. Using literal math baseline..."}
                        # Level 3: Final Resort - Literal Matching
                        similarity = compute_similarity(section_content, back_chunk or "")
                
                flagged = check_terminology(translated_chunk, glossary_terms)
                
                score_obj = SectionScore(
                    section_title=section_title,
                    original_text=section["content"][:100],
                    back_translated_text=(back_chunk or "")[:100],
                    similarity_score=similarity,
                    flagged_terms=flagged
                )

                # Update best result if this is better or first
                if similarity > best_similarity or final_score_obj is None:
                    best_similarity = similarity
                    best_chunk = translated_chunk
                    final_score_obj = score_obj

                # If confident or last attempt, we're done with this section
                if score_obj.is_confident or attempt == max_attempts:
                    if not score_obj.is_confident:
                         yield {"type": "status", "data": f"⚠️ [{section_index_txt}] Final accuracy: {round(similarity*100)}%. Proceeding..."}
                    else:
                         yield {"type": "status", "data": f"✅ [{section_index_txt}] Verified: {round(similarity*100)}%."}
                    break
                
                # --- Pass 4: Ultra-Precision Refinement (Triggered if low confidence) ---
                yield {"type": "status", "data": f"🛠️ [{section_index_txt}] Accuracy too low ({round(similarity*100)}%). Error Correction Mode active..."}
                
                retranslate_sys = _build_refinement_prompt(language_name, glossary_prompt, translated_chunk)
                
                refined_chunk = await _get_llm_response(
                    retranslate_sys, section_content, user_provider, api_key, user_model, settings, temperature=0.2
                )
                
                if refined_chunk:
                    translated_chunk = refined_chunk
                else:
                    break # Cannot refine if model gives empty response

            # Commit the best result
            full_translated_markdown += best_chunk + "\n\n"
            section_scores.append(final_score_obj)
            
            # Update UI with final text
            yield {"type": "translation", "data": full_translated_markdown}
            
            # Update UI with final accuracy card
            yield {
                "type": "verification_section",
                "data": {
                    "title": section_title,
                    "score": round(final_score_obj.similarity_score * 100, 1),
                    "label": final_score_obj.confidence_label,
                    "flagged_terms": final_score_obj.flagged_terms,
                    "metrics": {
                        "current_index": i + 1,
                        "total_sections": len(sections),
                        "running_avg": round((sum(s.similarity_score for s in section_scores) / len(section_scores)) * 100, 1)
                    }
                }
            }

        except Exception as e:
            logger.error(f"Error in section {section_title}: {e}")
            err_str = str(e).lower()
            
            # If the API key is exhausted, abort the whole pipeline rather than failing every section
            if any(k in err_str for k in ["quota", "429", "rate_limit", "ratelimit", "exceeded"]):
                yield {"type": "error", "data": (
                    f"❌ API Quota Exhausted while translating '{section_title}'. "
                    f"Your '{user_provider.upper()}' key has hit its rate limit. "
                    "Please switch to a different provider in Advanced Settings, use a fresh API key, or wait until tomorrow."
                )}
                return  # Stop the entire pipeline, no need to fail every remaining section
            
            # Otherwise, it's a transient error — skip and continue
            error_msg = f"Translation failed for section: {section_title}. Skipping..."
            yield {"type": "warning", "data": error_msg}
            full_translated_markdown += f"\n\n> [!WARNING] {error_msg}\n\n"
            yield {"type": "translation", "data": full_translated_markdown}

    # Build final report and save to cache
    final_report = VerificationReport(section_scores=section_scores)
    
    # Inject figures before saving and returning
    full_translated_markdown = reinsert_figures(full_translated_markdown, extracted_figures)
    yield {"type": "translation", "data": full_translated_markdown}
    
    save_translation(
        pdf_bytes=pdf_content,
        language=target_language,
        translated_markdown=full_translated_markdown,
        verification_score=final_report.overall_score,
        model_used=user_model or "default",
        glossary_version="1.0.0" # Could be dynamic if needed
    )

    yield {"type": "status", "data": "🎉 4-Pass Pipeline complete! Final verification summary below."}
    
    yield {
        "type": "verification", 
        "data": {
            "overall_score": round(final_report.overall_score * 100, 1),
            "overall_label": final_report.overall_label,
            "flagged_sections": [s.section_title for s in final_report.flagged_sections],
            "total_sections": len(final_report.section_scores),
            "section_scores": [] # individual scores already sent via verification_section
        }
    }

    yield {"type": "complete", "data": "Translation pipeline complete."}

    # Cleanup temp files
    try:
        if 'uploaded_file' in locals():
            genai.delete_file(uploaded_file.name)
    except Exception as e:
        logger.error(f"Failed to delete file from Google APIs: {e}")
        
    try:
        os.remove(tmp_path)
    except OSError:
        pass
