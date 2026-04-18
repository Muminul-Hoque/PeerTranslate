import json
import os
import time
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted
from dotenv import load_dotenv

BASE_DIR = r"E:\antigravity\PeerTranslate"
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=env_path, override=True)

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("FATAL: No API key found at " + env_path, flush=True)
    exit(1)

genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-flash-latest") # Use lighter model to reduce token/RPM issues

supported_langs = {
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

BASE_DIR = r"E:\antigravity\PeerTranslate"

for lang_code, lang_name in supported_langs.items():
    lang_dir = os.path.join(BASE_DIR, "glossaries", lang_code)
    os.makedirs(lang_dir, exist_ok=True)
    
    for domain in domains:
        out_path = os.path.join(lang_dir, f"{domain}.json")
        if os.path.exists(out_path):
            continue
            
        bn_path = os.path.join(BASE_DIR, "glossaries", "bn", f"{domain}.json")
        with open(bn_path, "r", encoding="utf-8") as f:
            bn_data = json.load(f)
            
        english_terms = list(bn_data["terms"].keys())
        
        prompt = f"""You are a translator for {lang_name}. Return ONLY a raw JSON object string mapping these English terms to their {lang_name} translations. For highly technical ML/CS terms, transliterate them and add the original English in parentheses. Terms to translate: {json.dumps(english_terms)}"""
        
        print(f"Generating {lang_code}/{domain} ...", flush=True)
        success = False
        retries = 0
        while not success and retries < 5:
            try:
                response = model.generate_content(prompt)
                result_json = response.text.replace('```json', '').replace('```', '').strip()
                translated_dict = json.loads(result_json)
                
                final_data = {
                    "language": lang_name,
                    "domain": domain,
                    "terms": translated_dict
                }
                
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, ensure_ascii=False, indent=4)
                
                success = True
                time.sleep(5)  # Stay safely under 15 RPM limit
                
            except ResourceExhausted as e:
                print(f"Rate limited. Sleeping 45 seconds... {e}", flush=True)
                time.sleep(45)
                retries += 1
            except Exception as e:
                print(f"Failed parsing {lang_code}/{domain}, error: {e}. Retrying.")
                time.sleep(5)
                retries += 1

print("Done generating all glossaries!")
