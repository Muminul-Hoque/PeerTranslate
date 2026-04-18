import os
import json
from pathlib import Path

BASE_DIR = Path(r"E:\antigravity\PeerTranslate")
GLOSSARY_DIR = BASE_DIR / "glossaries"

languages = [
    "hi", "ta", "ur", "es", "fr", "de", "ja", 
    "ko", "zh", "ar", "pt", "ru", "sw", "tr"
]

domains = [
    "cs", "ml", "math", "statistics",
    "physics", "astronomy", "chemistry", "biology", "earth_sciences",
    "medicine", "engineering", "materials_science", "agriculture",
    "economics", "psychology", "sociology", "political_science",
    "law", "business", "linguistics", "general_academic"
]

count = 0
for lang in languages:
    lang_dir = GLOSSARY_DIR / lang
    os.makedirs(lang_dir, exist_ok=True)
    
    for domain in domains:
        file_path = lang_dir / f"{domain}.json"
        
        # Only create if it literally does not exist (protects my injected ones)
        if not file_path.exists():
            data = {
                "domain": domain,
                "language": lang,
                "version": "1.0.0",
                "contributors": [],
                "terms": {}
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            count += 1

print(f"Created {count} boilerplate files for community contributions.")
