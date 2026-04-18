import os
import json
from pathlib import Path

BASE_DIR = Path(r"E:\antigravity\PeerTranslate")
GLOSSARY_DIR = BASE_DIR / "glossaries"

# Hardcoded pristine dictionaries directly from AI's internal knowledge base
knowledge_base = {
    "hi": {
        "cs": {
            "algorithm": "अल्गोरिदम (algorithm)",
            "data structure": "डेटा संरचना (data structure)",
            "artificial intelligence": "कृत्रिम बुद्धिमत्ता (artificial intelligence)",
            "machine learning": "मशीन लर्निंग (machine learning)",
            "cloud computing": "क्लाउड कंप्यूटिंग (cloud computing)",
            "neural network": "न्यूरल नेटवर्क (neural network)"
        },
        "medicine": {
            "vaccine": "टीका (vaccine)",
            "pathogen": "रोगजनक (pathogen)",
            "antibody": "प्रतिपिंड (antibody)",
            "diagnosis": "रोग का निदान (diagnosis)",
            "epidemiology": "महामारी विज्ञान (epidemiology)",
            "oncology": "अर्बुद विज्ञान (oncology)"
        },
        "physics": {
            "quantum mechanics": "क्वांटम यांत्रिकी (quantum mechanics)",
            "relativity": "सापेक्षता (relativity)",
            "thermodynamics": "ऊष्मागतिकी (thermodynamics)",
            "momentum": "संवेग (momentum)",
            "gravity": "गुरुत्वाकर्षण (gravity)"
        }
    },
    "es": {
        "cs": {
            "algorithm": "algoritmo (algorithm)",
            "data structure": "estructura de datos (data structure)",
            "artificial intelligence": "inteligencia artificial (artificial intelligence)",
            "machine learning": "aprendizaje automático (machine learning)",
            "cloud computing": "computación en la nube (cloud computing)",
            "neural network": "red neuronal (neural network)"
        },
        "medicine": {
            "vaccine": "vacuna (vaccine)",
            "pathogen": "patógeno (pathogen)",
            "antibody": "anticuerpo (antibody)",
            "diagnosis": "diagnóstico (diagnosis)",
            "epidemiology": "epidemiología (epidemiology)",
            "oncology": "oncología (oncology)"
        },
        "physics": {
            "quantum mechanics": "mecánica cuántica (quantum mechanics)",
            "relativity": "relatividad (relativity)",
            "thermodynamics": "termodinámica (thermodynamics)",
            "momentum": "momento (momentum)",
            "gravity": "gravedad (gravity)"
        }
    },
    "fr": {
        "cs": {
            "algorithm": "algorithme (algorithm)",
            "data structure": "structure de données (data structure)",
            "artificial intelligence": "intelligence artificielle (artificial intelligence)",
            "machine learning": "apprentissage automatique (machine learning)",
            "cloud computing": "informatique en nuage (cloud computing)",
            "neural network": "réseau de neurones (neural network)"
        },
        "medicine": {
            "vaccine": "vaccin (vaccine)",
            "pathogen": "agent pathogène (pathogen)",
            "antibody": "anticorps (antibody)",
            "diagnosis": "diagnostic (diagnosis)",
            "epidemiology": "épidémiologie (epidemiology)",
            "oncology": "oncologie (oncology)"
        },
        "physics": {
            "quantum mechanics": "mécanique quantique (quantum mechanics)",
            "relativity": "relativité (relativity)",
            "thermodynamics": "thermodynamique (thermodynamics)",
            "momentum": "quantité de mouvement (momentum)",
            "gravity": "gravité (gravity)"
        }
    }
}

count = 0
for lang, domains in knowledge_base.items():
    lang_dir = GLOSSARY_DIR / lang
    os.makedirs(lang_dir, exist_ok=True)
    
    for domain, terms in domains.items():
        file_path = lang_dir / f"{domain}.json"
        
        data = {
            "domain": domain,
            "language": lang,
            "version": "1.0.0",
            "contributors": ["Antigravity Root Generation"],
            "terms": terms
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        count += 1

print(f"Successfully injected {count} high-fidelity baseline dictionaries directly to disk.")
