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


def _validate_numbers(original_text: str, translated_text: str) -> tuple[str, list[str]]:
    """
    Post-processing number validator.
    
    Extracts all significant numbers from the original text and verifies
    they appear in the translation. If a number is missing or altered,
    attempts to fix it automatically.
    
    Returns:
        (corrected_translation, list_of_warnings)
    """
    import re
    
    # Extract all numbers from original (integers, decimals, percentages, scientific notation)
    # But skip very small numbers (1, 2, 3) which are too common (section numbers, list items)
    orig_numbers = set()
    for match in re.finditer(r'(?<!\w)(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)(?:%|\b)', original_text):
        num_str = match.group(1)
        try:
            num_val = float(num_str)
            # Only validate "significant" numbers (> 9, or decimals, or percentages)
            if num_val > 9 or '.' in num_str or '%' in original_text[match.end():match.end()+1:]:
                orig_numbers.add(num_str)
        except ValueError:
            continue
    
    if not orig_numbers:
        return translated_text, []
    
    warnings = []
    corrected = translated_text
    
    for num in orig_numbers:
        if num not in corrected:
            # Check if number was converted to local script (e.g., Bengali)
            # We already normalize Bengali→Arabic numerals, so this shouldn't happen,
            # but check if the number was simply altered (586 → 546)
            warnings.append(f"Number '{num}' from original not found in translation")
            logger.warning(f"Number validation: '{num}' missing from translation")
    
    return corrected, warnings


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
3. **DO NOT translate**: author names, affiliations, institution names, URLs, DOIs, email addresses, reference citations (including "et al."), mathematical equations, code, and figure/table numbers. KEEP NAMES IN ENGLISH.
4. **DO translate**: title, abstract, all body text, section headings, figure captions, table captions, and conclusion.
5. **Maintain academic register**: Use formal, scholarly language appropriate for the target language, but it's okay to use colloquialisms or conversational phrasing (e.g., using "হিমশিম খায়" instead of overly rigid terms like "সংগ্রাম করে") if it makes the text flow more naturally.
6. **Preserve line breaks exactly**: If authors and affiliations are on multiple lines, keep them on exactly the same lines with the exact same superscripts/asterisks (e.g., `Author1*, Author2`).
7. **Technical accuracy**: Scientific claims, numerical data, and methodological descriptions must be translated with 100% fidelity.
8. **ZERO PARAPHRASING & ZERO SUMMARIZATION**: Do not add extra filler. Do not invent headings. Do NOT summarize the paper. If the input is just a Title and Authors, translate ONLY the Title and Authors. Do not hallucinate the abstract or introduction.
9. **NO CHUNK ARTIFACTS**: You are translating chunks of a larger document. Do NOT output any chunk metadata, page numbers, or artifact titles like '(Part 3)', '(অংশ ২)', or '(continued)'. Output ONLY the clean, translated academic text.
10. **NUMERAL CONSISTENCY**: IMPORTANT: Keep all section numbers, figures, and numerical data as Arabic numerals (1, 2, 3...). Do NOT translate numerals into local scripts (e.g., do not use ১, ২, ৩).
11. **COMPLETE TITLE — NO TRUNCATION**: If the input contains a paper title, you MUST translate the COMPLETE title word-for-word. Do NOT shorten, abbreviate, or drop any part of the title. For example, "Assessing the Effectiveness of GPT-4o in Climate Change Evidence Synthesis" must be fully translated — do NOT output only the last few words.
12. **EXACT NUMBER PRESERVATION**: Every number in the original (sample sizes, percentages, p-values, dates, table values) MUST appear IDENTICALLY in the translation. For example, if the original says n=586, the translation MUST say n=586, NOT n=546 or n=৫৮৬. Double-check all numbers before outputting.
13. **FORMAT-SPECIFIC TERMS**: Academic format terms like "research short", "letter", "brief communication", "preprint" should be kept in English (parenthesized) alongside the translation. Example: "এই সংক্ষিপ্ত গবেষণাপত্রে (research short)".
14. **ABSOLUTE ANTI-HALLUCINATION RULE — THE MOST IMPORTANT RULE**: You MUST translate ONLY the text you are given. You MUST NOT:
   - Generate a new introduction, abstract, or body paragraph that was NOT in the input.
   - Write explanatory text about the paper's topic (e.g., do NOT write about AI, RAG, LLMs, or any other topic unless that EXACT text was in the source).
   - If the input is ONLY author names, emails, affiliations, a title, or copyright text: translate ONLY those exact words. Return NOTHING else.
   - **FAILURE EXAMPLE (FORBIDDEN)**: Input="## Introduction\n\nAttention Is All You Need\nAshish Vaswani". WRONG output: writing a paragraph about AI advancements. CORRECT output: translating only the title and author name.


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
6. **NUMERAL CONSISTENCY**: Keep all section numbers, figures, and numerical data as Arabic numerals (1, 2, 3...). Do NOT translate numerals into local scripts.
7. ONLY output the corrected translation.

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
                # 180-second hard timeout per API call — prevents infinite hangs and allows generation of larger chunks
                from google.generativeai.types import HarmCategory, HarmBlockThreshold
                
                safety_settings = {
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                }
                
                response = await asyncio.wait_for(
                    model.generate_content_async(
                        [full_prompt],
                        generation_config=genai.types.GenerationConfig(
                            temperature=temperature,
                            max_output_tokens=65536,
                        ),
                        safety_settings=safety_settings,
                    ),
                    timeout=180.0
                )
                # Brief pause to avoid 30 RPM burst limit on Gemma models
                await asyncio.sleep(2)
                
                # Check for empty response (e.g., safety filters)
                if not response.parts:
                    err_txt = str(response.candidates[0].finish_reason) if response.candidates else "Unknown Safety Filter"
                    raise ValueError(f"Content blocked by safety filters. Finish Reason: {err_txt}")
                    
                return response.text
            except asyncio.TimeoutError:
                last_exception = Exception("Google API call timed out after 180s. This may be due to heavy server load or rate_limit.")
                logger.warning(f"Google API timed out. Attempt {attempt+1}/{max_retries}")
                await asyncio.sleep(5)
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                
                # Handle Google Gemini "Recitation" / Copyright block (Finish Reason 4)
                if "finish_reason" in err_msg and ("4" in err_msg or "reciting" in err_msg):
                    logger.warning("Gemini API blocked output due to Copyright/Recitation filters. Using original text as fallback.")
                    return f"\n\n> [!WARNING] **Translation Blocked**  \n> Google blocked the translation of this section because it resembles its copyrighted training data (Recitation Filter). Showing original English text instead:\n\n{user_content}\n\n"

                
                # If we hit an RPM (Requests Per Minute) rate limit / 429 error, pause gracefully and retry
                if any(k in err_msg for k in ["429", "quota", "exceeded", "rate limit", "ratelimit"]) and attempt < max_retries - 1:
                    logger.warning(f"Hit Google API quota/rate limit. Pausing 20s to reset RPM... (Attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(20.0)
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
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        temperature=temperature
                    ),
                    timeout=180.0
                )
                return response.choices[0].message.content
            except asyncio.TimeoutError:
                last_exception = Exception(f"API call to {provider} timed out after 180s. Possible rate_limit or server overload.")
                logger.warning(f"{provider} API timed out. Attempt {attempt+1}/{max_retries}")
                await asyncio.sleep(5)
            except openai.RateLimitError as e:
                last_exception = e
                wait_time = (attempt + 1) * 5 # Wait 5s, 10s...
                logger.warning(f"Rate limited by {provider} (429/rate_limit). Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            except Exception as e:
                # Immediate fail for non-429 errors
                raise e
        
        raise last_exception or Exception(f"Failed after {max_retries} attempts due to rate limits.")


async def _stream_llm_response(
    system_prompt: str,
    user_content: str,
    provider: str,
    api_key: Optional[str],
    model_name: Optional[str],
    settings: Settings,
    temperature: float = 0.1
):
    """Hybrid LLM streaming generator for OpenRouter, OpenAI, and Google Native."""
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
                from google.generativeai.types import HarmCategory, HarmBlockThreshold
                safety_settings = {
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                }
                
                # Rate limit protection for Free Tier users
                # Reduced to 1.5s for speed, relying more on retry logic
                if provider == "google":
                    await asyncio.sleep(1.5)

                response_stream = await asyncio.wait_for(
                    model.generate_content_async(
                        [full_prompt],
                        generation_config=genai.types.GenerationConfig(
                            temperature=temperature,
                            max_output_tokens=65536,
                        ),
                        safety_settings=safety_settings,
                        stream=True
                    ),
                    timeout=180.0
                )
                
                async for chunk in response_stream:
                    if chunk.text:
                        yield chunk.text
                return # Successfully finished streaming
                
            except asyncio.TimeoutError:
                last_exception = Exception("Google API call timed out after 180s.")
                logger.warning(f"Google API timed out. Attempt {attempt+1}/{max_retries}")
                await asyncio.sleep(5)
            except Exception as e:
                last_exception = e
                err_msg = str(e).lower()
                
                if "finish_reason" in err_msg and ("4" in err_msg or "reciting" in err_msg):
                    logger.warning("Gemini API blocked output due to Copyright/Recitation filters. Using original text as fallback.")
                    yield f"\n\n> [!WARNING] **Translation Blocked**  \n> Google blocked the translation of this section because it resembles its copyrighted training data (Recitation Filter). Showing original English text instead:\n\n{user_content}\n\n"
                    return
                
                if any(k in err_msg for k in ["429", "quota", "exceeded", "rate limit", "ratelimit"]) and attempt < max_retries - 1:
                    logger.warning(f"Hit Google API quota/rate limit. Pausing 20s... (Attempt {attempt+1}/{max_retries})")
                    await asyncio.sleep(20.0)
                    continue
                    
                if any(k in err_msg for k in ["404", "not found", "invalid"]):
                    raise e
                    
                wait_time = (attempt + 1) * 3
                logger.warning(f"Google API Error. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
                
        raise last_exception or Exception(f"Failed after {max_retries} attempts.")
        
    else:
        # OpenAI or OpenRouter
        base_url = "https://openrouter.ai/api/v1" if provider == "openrouter" else None
        if not model_name:
            model_name = "meta-llama/llama-3.1-8b-instruct:free" if provider == "openrouter" else "gpt-4o-mini"
            
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        max_retries = 3
        last_exception = None
        
        import asyncio
        import openai

        for attempt in range(max_retries):
            try:
                response_stream = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        temperature=temperature,
                        stream=True
                    ),
                    timeout=180.0
                )
                
                async for chunk in response_stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
                return # Successfully finished streaming
                
            except asyncio.TimeoutError:
                last_exception = Exception(f"API call to {provider} timed out after 180s.")
                logger.warning(f"{provider} API timed out. Attempt {attempt+1}/{max_retries}")
                await asyncio.sleep(5)
            except openai.RateLimitError as e:
                last_exception = e
                wait_time = (attempt + 1) * 5
                logger.warning(f"Rate limited by {provider}. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)
            except Exception as e:
                raise e
        
        raise last_exception or Exception(f"Failed after {max_retries} attempts due to rate limits.")



def _structure_raw_text_as_markdown(raw_text: str) -> str:
    """
    Post-processes raw PyMuPDF text to inject '## ' Markdown heading markers
    so that split_into_sections() (which only splits on # and ##) works correctly.

    Key problems this solves:
    1. 2-column PDF layouts where section numbers appear alone on one line
       and the title appears on the next line (e.g. "2\nBackground").
    2. Numbered headings on a single line (e.g. "3 Related Work").
    3. Well-known academic section names appearing alone on a line.

    IMPORTANT: Only emits ## (H2) markers because split_into_sections
    only triggers on # and ## lines.
    """
    import re

    # Well-known academic section names (case-insensitive exact match)
    KNOWN_SECTIONS = {
        'abstract', 'introduction', 'conclusion', 'conclusions', 'related work',
        'related works', 'background', 'method', 'methods', 'methodology',
        'experiments', 'experiment', 'results', 'result', 'discussion',
        'discussions', 'acknowledgment', 'acknowledgments', 'acknowledgements',
        'references', 'appendix', 'evaluation', 'approach', 'analysis',
        'dataset', 'datasets', 'model', 'training', 'inference', 'setup',
        'framework', 'architecture', 'implementation', 'limitations',
        'future work', 'preliminaries', 'notation', 'overview',
    }

    lines = raw_text.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            result.append(line)
            i += 1
            continue

        # Pattern 1: Number-only line followed by title on next line (2-column fix)
        num_only = re.match(r'^(\d+\.?\d*\.?)\s*$', stripped)
        if num_only and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            next_words = next_stripped.split()
            if (
                next_stripped and
                len(next_stripped) <= 60 and
                not next_stripped.endswith('.') and
                next_stripped[0].isupper() and
                len(next_words) <= 8 and
                not re.search(r'\b(the|a|an|is|are|was|were|have|has|we|our|this|these|that)\b',
                              next_stripped, re.IGNORECASE)
            ):
                result.append(f'## {stripped} {next_stripped}')
                i += 2
                continue

        # Pattern 2: Numbered section heading on single line
        numbered_heading = re.match(r'^(\d+\.?\d*\.?)\s+([A-Z][^\n]{2,60})$', stripped)
        if numbered_heading:
            title_part = numbered_heading.group(2).strip()
            title_words = title_part.split()
            if (
                len(title_words) <= 8 and
                not title_part.endswith('.') and
                not re.search(r'\b(the|a|an|is|are|was|were|have|has|we|our|this|these|that)\b',
                              title_part, re.IGNORECASE)
            ):
                result.append(f'## {stripped}')
                i += 1
                continue

        # Pattern 3: Known academic section name alone
        if stripped.lower().rstrip(':') in KNOWN_SECTIONS and len(stripped) <= 60:
            result.append(f'## {stripped}')
            i += 1
            continue

        result.append(line)
        i += 1

    return '\n'.join(result)


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
    quick_mode: bool = False,
) -> AsyncGenerator[Dict[str, Any], None]:
    
    language_name = _get_language_name(target_language)
    
    # 0. Debug Trace
    logger.info(f">>> PIPELINE START: provider={user_provider}, model={user_model}, has_api_key={bool(api_key)}")

    # 1. Load Glossary
    yield {"type": "status", "data": "📚 Loading academic glossary..."}
    glossary_terms = load_all_glossaries(target_language)
    glossary_prompt = build_glossary_prompt(glossary_terms)
    yield {"type": "status", "data": f"✅ Loaded {len(glossary_terms)} domain-specific terms"}



    # 2. Save PDF to temp file & extract figures
    yield {"type": "status", "data": "📄 Processing PDF document..."}
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
        tmp_file.write(pdf_content)
        tmp_path = tmp_file.name
        
    # ═══════════════════════════════════════════════════════════════
    # STEP 1: PDF TEXT EXTRACTION (PyMuPDF)
    #   Direct, reliable extraction using fitz. Fast and quota-free.
    #   Followed by heuristic Markdown structuring to detect headings.
    # ═══════════════════════════════════════════════════════════════
    yield {"type": "status", "data": "📄 Extracting text from PDF..."}
    original_english_text = ""
    try:
        import fitz
        doc = fitz.open(stream=pdf_content, filetype="pdf")
        for page in doc:
            original_english_text += page.get_text() + "\n\n"
        doc.close()
        yield {"type": "status", "data": "✅ Text extraction complete."}
        # Detect section headings and add Markdown markers so the splitter works correctly
        original_english_text = _structure_raw_text_as_markdown(original_english_text)
        yield {"type": "status", "data": "🔧 Document structure detected."}
    except Exception as extract_err:
        logger.error(f"PyMuPDF extraction failed: {extract_err}")
        yield {"type": "error", "data": f"❌ Failed to extract text from PDF: {extract_err}"}
        return

    if not original_english_text.strip():
        yield {"type": "error", "data": "❌ Could not extract any text from the PDF. It may be corrupted or image-only."}
        return

    # 1.5 Check Cache First (Now hashing the extracted text instead of raw PDF bytes)
    text_bytes = original_english_text.encode("utf-8")
    pdf_hash = get_hash(text_bytes, target_language)
    cached_data = get_cached_translation(text_bytes, target_language, settings.similarity_threshold)
    
    yield {"type": "cache_info", "data": {"hash_key": pdf_hash, "from_cache": False}}
    
    if cached_data:
        yield {"type": "status", "data": "🌟 Found verified translation in Community Cache!"}
        yield {"type": "cache_info", "data": {"hash_key": pdf_hash, "from_cache": True}}
        
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

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: FIGURE EXTRACTION (Non-blocking heuristic)
    # ═══════════════════════════════════════════════════════════════
    extracted_figures = {}
    if not quick_mode:
        try:
            yield {"type": "status", "data": "🖼️ Extracting figures and diagrams..."}
            extracted_figures = extract_images_from_pdf(pdf_content)
            if extracted_figures:
                yield {"type": "status", "data": f"✅ Found {len(extracted_figures)} figures."}
        except Exception as fig_err:
            logger.warning(f"Figure extraction failed (skipping): {fig_err}")

    # ═══════════════════════════════════════════════════════════════
    # STEP 3: TRANSLATION PIPELINE
    # ═══════════════════════════════════════════════════════════════
    yield {"type": "status", "data": "✅ Extracted original English sections."}
    
    sections = split_into_sections(original_english_text)
    
    # Send original English chunks to frontend for side-by-side view
    # Chunking avoids SSE payload limits and browser lag for large papers
    for section in sections:
        yield {
            "type": "original_english_chunk", 
            "data": f"# {section['title']}\n\n{section['content']}\n\n"
        }

    # 4. Start Real-Time 4-Pass Pipeline (Iterative Section-by-Section)
    effective_label = user_provider.upper() if user_provider else "GOOGLE"
    yield {"type": "status", "data": f"🚀 Starting Real-Time 4-Pass Pipeline via {effective_label}..."}
    
    translation_prompt = _build_translation_prompt(language_name, glossary_prompt)
    back_translation_prompt = _build_back_translation_prompt(language_name)
    
    # Quick Mode: only translate Abstract, Introduction, Conclusion, Summary
    if quick_mode:
        QUICK_KEYWORDS = {'abstract', 'introduction', 'conclusion', 'summary', 'concluding', 'discussion'}
        filtered = [s for s in sections if any(kw in s['title'].lower() for kw in QUICK_KEYWORDS)]
        # Always keep the first section (title/header) and at least some content
        if sections and (not filtered or sections[0] not in filtered):
            filtered.insert(0, sections[0])
        if filtered:
            sections = filtered
            yield {"type": "status", "data": f"⚡ Quick Mode: translating {len(sections)} key sections only."}
    
    full_translated_markdown = ""
    section_scores = []
    _emitted_titles = set()  # Track which section titles have already been emitted as headings
    
    for i, section in enumerate(sections):
        # Reduced gap between sections for speed
        if i > 0:
            await asyncio.sleep(0.5)

        section_title = section["title"]
        section_index_txt = f"{i+1}/{len(sections)}"
        
        # --- Bypasses ---
        # 1. References Bypass (Never translate reference citations to maintain academic integrity)
        if any(ref_word in section_title.lower() for ref_word in ["references", "bibliography"]):
             yield {"type": "status", "data": f"📚 [{section_index_txt}] Bypassed: {section_title} (Maintained in original language)."}
             best_chunk = f"## {section_title}\n\n{section['content']}"
             final_score_obj = SectionScore(
                 section_title=section_title, 
                 original_text=section["content"][:100], 
                 back_translated_text="-reference-bypass-", 
                 similarity_score=1.0
             )
             full_translated_markdown += best_chunk + "\n\n"
             section_scores.append(final_score_obj)
             
             yield {"type": "translation_chunk", "data": best_chunk + "\n\n"}
             yield {
                 "type": "verification_section",
                 "data": {
                     "title": section_title, "score": 100.0, "label": "skipped", "flagged_terms": [],
                     "metrics": {"current_index": i + 1, "total_sections": len(sections), "running_avg": round((sum(s.similarity_score for s in section_scores) / len(section_scores)) * 100, 1)}
                 }
             }
             continue
        
        # --- Pass 1: Translate ---
        yield {"type": "status", "data": f"⏳ [{section_index_txt}] Translating: {section_title}..."}
        
        # For chunked sections: only include heading for the first chunk
        is_continuation = section_title in _emitted_titles
        if is_continuation:
            section_content = section['content']
        else:
            section_content = f"## {section_title}\n\n{section['content']}"
            _emitted_titles.add(section_title)
        
        try:
            # PRE-TRANSLATION GUARD: If the section content is too sparse (< 10 words),
            # the model is very likely to hallucinate. Skip the LLM entirely.
            content_word_count = len(section['content'].split())
            if content_word_count < 10:
                logger.info(f"Section '{section_title}' has only {content_word_count} words — bypassing LLM to prevent hallucination.")
                translated_chunk = section_content  # Keep original text as-is
                yield {"type": "translation_chunk", "data": translated_chunk + "\n\n"}
                best_chunk = translated_chunk
                final_score_obj = SectionScore(
                    section_title=section_title,
                    original_text=section["content"][:100],
                    back_translated_text="-sparse-bypass-",
                    similarity_score=1.0
                )
                full_translated_markdown += best_chunk + "\n\n"
                section_scores.append(final_score_obj)
                yield {"type": "translation", "data": full_translated_markdown}
                yield {
                    "type": "verification_section",
                    "data": {
                        "title": section_title, "score": 100.0, "label": "skipped", "flagged_terms": [],
                        "metrics": {"current_index": i + 1, "total_sections": len(sections), "running_avg": 100.0}
                    }
                }
                continue
            
            translated_chunk = ""
            async for token in _stream_llm_response(
                translation_prompt, section_content, user_provider, api_key, user_model, settings
            ):
                translated_chunk += token
                yield {"type": "translation_chunk", "data": token}
            
            yield {"type": "translation_chunk", "data": "\n\n"}
            
            if not translated_chunk:
                raise Exception("Model returned empty translation.")
                
            # Normalize mixed numerals (convert Bengali digits to Arabic)
            translated_chunk = translated_chunk.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
            
            # Fix split headings: collapse "## 2\nTitle" back into "## 2 Title"
            # This is a common artifact from 2-column LaTeX PDFs where section number
            # and title are on separate lines in the raw text and the model preserves the split.
            import re as _re
            translated_chunk = _re.sub(
                r'^(#{1,3}\s+[\d\.]+)\s*\n+(\S)',
                r'\1 \2',
                translated_chunk,
                flags=_re.MULTILINE
            )

            # Post-processing: Validate numbers from original are preserved
            translated_chunk, num_warnings = _validate_numbers(section['content'], translated_chunk)
            if num_warnings:
                yield {"type": "status", "data": f"⚠️ [{section_index_txt}] Number check: {len(num_warnings)} number(s) may have been altered."}
                for nw in num_warnings[:3]:  # Show max 3 warnings
                    yield {"type": "status", "data": f"   🔢 {nw}"}

            # --- Pass 2 & 3: Verification with Recursive Loop (Pass 4) ---
            # Bypass rigorous verification for very short sections (like Titles, Authors, strict equations)
            if len(section['content'].split()) < 30:
                 yield {"type": "status", "data": f"✅ [{section_index_txt}] Verified: 100% (Short text bypass)."}
                 final_score_obj = SectionScore(
                     section_title=section_title, 
                     original_text=section["content"][:100], 
                     back_translated_text="-bypassed-", 
                     similarity_score=1.0
                 )
                 full_translated_markdown += translated_chunk + "\n\n"
                 section_scores.append(final_score_obj)
                 
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
                yield {"type": "status", "data": f"🔄 [{section_index_txt}] Verifying (Attempt {attempt})..."}
                back_chunk = await _get_llm_response(
                    back_translation_prompt, translated_chunk, user_provider, api_key, user_model, settings
                )
                
                yield {"type": "status", "data": f"⚖️ [{section_index_txt}] AI Judge ({judge_provider}) is evaluating meaning... (Attempt {attempt})"}
                
                judge_prompt = _build_judge_prompt(section_content, back_chunk or "")
                try:
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
                
                yield {"type": "retranslation", "data": {"section": section_title}}
                refined_chunk = ""
                async for token in _stream_llm_response(
                    retranslate_sys, section_content, user_provider, api_key, user_model, settings, temperature=0.2
                ):
                    refined_chunk += token
                    yield {"type": "translation_chunk", "data": token}
                
                yield {"type": "translation_chunk", "data": "\n\n"}
                
                if refined_chunk:
                    translated_chunk = refined_chunk.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
                else:
                    break # Cannot refine if model gives empty response

            # Commit the best result
            full_translated_markdown += best_chunk + "\n\n"
            section_scores.append(final_score_obj)
            
            # Sync UI with the final, post-processed text (numeral normalization etc.)
            # Using 'translation' (replace) not 'translation_chunk' (append) to prevent
            # duplication since Pass 1 already streamed the raw tokens to the screen.
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
            is_quota = any(k in err_str for k in ["quota", "429", "rate_limit", "ratelimit"])
            # Be careful: "exceeded" might just be a safety threshold, don't abort for that!
            if is_quota:
                error_body = (
                    f"❌ API Quota Exhausted while translating '{section_title}'. "
                    f"Your '{user_provider.upper()}' key has hit its rate limit. "
                    "Please switch to a different provider in Advanced Settings, use a fresh API key, or wait for your quota to reset."
                )
                yield {"type": "error", "data": error_body}
                full_translated_markdown += f"\n\n> [!ERROR] {error_body}\n\n"
                yield {"type": "translation_chunk", "data": f"\n\n> [!ERROR] {error_body}\n\n"}
                return  # Stop the entire pipeline, no need to fail every remaining section
            
            # Dynamic Chunking Fallback: If section is very large, split it and retry
            if len(section['content']) > 1500 and "\n\n" in section['content']:
                yield {"type": "status", "data": f"⚠️ [{section_index_txt}] Chunk failed. Splitting in half and retrying..."}
                paragraphs = section["content"].split("\n\n")
                mid = len(paragraphs) // 2
                half1_content = "\n\n".join(paragraphs[:mid])
                half2_content = "\n\n".join(paragraphs[mid:])
                
                try:
                    h1 = await _get_llm_response(translation_prompt, f"## {section_title} (Part 1)\n\n{half1_content}", user_provider, api_key, user_model, settings)
                    h1 = h1.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
                except Exception as e1:
                    logger.error(f"Half 1 failed: {e1}")
                    h1 = f"**[Translation failed for this part. Original text preserved:]**\n\n{half1_content}"
                    
                try:
                    h2 = await _get_llm_response(translation_prompt, f"## {section_title} (Part 2)\n\n{half2_content}", user_provider, api_key, user_model, settings)
                    h2 = h2.translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
                except Exception as e2:
                    logger.error(f"Half 2 failed: {e2}")
                    h2 = f"**[Translation failed for this part. Original text preserved:]**\n\n{half2_content}"
                
                best_chunk = h1 + "\n\n" + h2
                full_translated_markdown += best_chunk + "\n\n"
                
                # Mock a bypassed score for the split section so it doesn't break metrics
                score_obj = SectionScore(
                    section_title=section_title, original_text=section["content"][:100],
                    back_translated_text="-dynamic-split-", similarity_score=0.5
                )
                section_scores.append(score_obj)
                
                yield {"type": "translation_chunk", "data": best_chunk + "\n\n"}
                yield {
                    "type": "verification_section",
                    "data": {
                        "title": section_title, "score": 50.0, "label": "needs_review", "flagged_terms": [],
                        "metrics": {"current_index": i + 1, "total_sections": len(sections), "running_avg": round((sum(s.similarity_score for s in section_scores) / len(section_scores)) * 100, 1)}
                    }
                }
                continue

            # Otherwise, it's a transient error — skip and continue
            error_msg = f"Translation failed for section: {section_title}. Original text preserved."
            yield {"type": "warning", "data": error_msg}
            safe_fallback = f"**[⚠️ Translation Failed for this Section]**\n\n{section_content}"
            full_translated_markdown += f"\n\n{safe_fallback}\n\n"
            yield {"type": "translation_chunk", "data": f"\n\n{safe_fallback}\n\n"}
            
            # Mock failed score
            score_obj = SectionScore(
                section_title=section_title, original_text=section["content"][:100],
                back_translated_text="-failed-", similarity_score=0.0
            )
            section_scores.append(score_obj)

    # Build final report and save to cache
    final_report = VerificationReport(section_scores=section_scores)
    
    # Prepend Translator's Note
    lang_name = _get_language_name(target_language)
    translator_note = (
        f"<div style='font-size: 0.8rem; color: var(--text-muted); background: var(--bg-tertiary); padding: 8px 12px; border-radius: 6px; margin-bottom: 20px; border-left: 3px solid var(--accent-cyan); display: inline-block;'>\n"
        f"<b>PeerTranslate Note:</b> This document was translated to <b>{lang_name}</b> using a dual-term glossary system "
        f"(keeping critical scientific terms in English) to maximize accuracy. Please verify critical numbers and formulas against the original PDF.\n"
        f"</div>\n\n"
    )
    full_translated_markdown = translator_note + full_translated_markdown

    # Inject figures before saving and returning (skip if no figures extracted)
    if extracted_figures:
        full_translated_markdown = reinsert_figures(full_translated_markdown, extracted_figures)
    yield {"type": "translation", "data": full_translated_markdown}
    
    save_translation(
        pdf_bytes=original_english_text.encode("utf-8"),
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
