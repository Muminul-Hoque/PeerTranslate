import os
import json
import time
import sys
import google.generativeai as genai
from pathlib import Path
from dotenv import load_dotenv

def log(msg):
    print(msg, flush=True)

# Load environment
BASE_DIR = Path(r"E:\antigravity\PeerTranslate")
load_dotenv(BASE_DIR / ".env")
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    log("Error: GEMINI_API_KEY not found.")
    exit(1)

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-2.5-flash")

# Configuration
languages = {
    "hi": "हिन्दी (Hindi)", "ta": "தமிழ் (Tamil)", "ur": "اردو (Urdu)",
    "es": "Español (Spanish)", "fr": "Français (French)", "de": "Deutsch (German)",
    "ja": "日本語 (Japanese)", "ko": "한국어 (Korean)", "zh": "中文 (Chinese)",
    "ar": "العربية (Arabic)", "pt": "Português (Portuguese)", "ru": "Русский (Russian)",
    "sw": "Kiswahili (Swahili)", "tr": "Türkçe (Turkish)",
}

domains = [
    "cs", "ml", "math", "statistics",
    "physics", "astronomy", "chemistry", "biology", "earth_sciences",
    "medicine", "engineering", "materials_science", "agriculture",
    "economics", "psychology", "sociology", "political_science",
    "law", "business", "linguistics", "general_academic"
]

def load_bn_seeds():
    log("Loading Bengali seed glossaries...")
    seeds = {}
    bn_dir = BASE_DIR / "glossaries" / "bn"
    for domain in domains:
        path = bn_dir / f"{domain}.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                seeds[domain] = json.load(f)["terms"]
        else:
            log(f"Warning: BN seed for {domain} missing.")
    return seeds

def batch_generate():
    seeds = load_bn_seeds()
    
    for lang_code, lang_name in languages.items():
        lang_dir = BASE_DIR / "glossaries" / lang_code
        os.makedirs(lang_dir, exist_ok=True)
        
        # Check if already fully generated
        existing_files = [f for f in domains if (lang_dir / f"{f}.json").exists()]
        if len(existing_files) == len(domains):
            log(f"Skipping {lang_code} (already complete with {len(existing_files)} files)")
            continue

        log(f"Processing {lang_code}... Requesting batch translation for 21 domains.")
        
        prompt = f"""
        You are an expert academic translator. 
        I am giving you 21 academic domain glossaries in English -> Bengali.
        Your task is to translate these exact terms into {lang_name} ({lang_code}).
        
        RULES:
        1. Keep the English term as the key.
        2. Provide the translation in {lang_name}.
        3. For technical terms (e.g., 'backpropagation'), use the native script but include the original English in parentheses.
        4. Return the result strictly as a valid JSON object where keys are domain names (e.g., "cs", "math") and values are the corresponding translated glossary objects.
        
        SOURCE BENGALI GLOSSARIES:
        {json.dumps(seeds, ensure_ascii=False, indent=1)}
        
        RETURN FORMAT:
        {{
            "cs": {{ "term": "translation", ... }},
            "math": {{ ... }},
            ... (all 21 domains)
        }}
        """

        try:
            start_time = time.time()
            response = model.generate_content(prompt)
            duration = time.time() - start_time
            log(f"API Response received in {duration:.1f}s. Parsing...")

            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:-3].strip()
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:-3].strip()
                
            batch_data = json.loads(raw_text)
            
            saved_count = 0
            for domain in domains:
                if domain in batch_data:
                    output_path = lang_dir / f"{domain}.json"
                    data = {
                        "domain": domain,
                        "language": lang_code,
                        "version": "1.0.0",
                        "contributors": ["PeerTranslate AI"],
                        "terms": batch_data[domain]
                    }
                    with open(output_path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=4, ensure_ascii=False)
                    saved_count += 1
            
            log(f"Success! Generated {saved_count}/21 files for {lang_code}.")
            time.sleep(15) 
            
        except Exception as e:
            log(f"Error processing {lang_code}: {e}")
            time.sleep(40)

if __name__ == "__main__":
    batch_generate()
    log("ALL GLOSSARIES GENERATED SUCCESSFULLY!")
