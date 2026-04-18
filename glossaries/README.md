# 🌍 Contributing Glossaries to PeerTranslate

Thank you for helping make academic knowledge accessible in every language!

## What Are Glossaries?

Glossaries are community-curated JSON files that map English academic terms to their correct translations in specific languages. When PeerTranslate translates a research paper, it **locks** these terms so the AI uses the exact, verified translation instead of guessing.

## Directory Structure

```
glossaries/
├── bn/                        # Bengali (বাংলা)
│   ├── cs.json               # Computer Science terms
│   ├── ml.json               # Machine Learning terms
│   └── general_academic.json # General academic terms
├── hi/                        # Hindi (next!)
│   └── ...
└── README.md                 # You are here
```

## How to Add a New Language

1. **Fork** this repository
2. Create a new folder: `glossaries/{language_code}/`
   - Use [ISO 639-1 codes](https://en.wikipedia.org/wiki/List_of_ISO_639-1_codes) (e.g., `hi` for Hindi, `ta` for Tamil, `es` for Spanish)
3. Create at least one JSON file (e.g., `general_academic.json`)
4. Follow the format below
5. Submit a **Pull Request**!

## JSON Format

```json
{
    "domain": "machine_learning",
    "language": "bn",
    "version": "1.0.0",
    "contributors": ["Your Name"],
    "terms": {
        "attention mechanism": "অ্যাটেনশন মেকানিজম",
        "gradient descent": "গ্রেডিয়েন্ট ডিসেন্ট",
        "backpropagation": "ব্যাকপ্রোপাগেশন"
    }
}
```

### Fields

| Field | Description |
|---|---|
| `domain` | One of: `cs`, `ml`, `general_academic`, or a new domain you propose |
| `language` | ISO 639-1 language code |
| `version` | Semantic versioning (bump when adding terms) |
| `contributors` | List of people who contributed to this glossary |
| `terms` | English → Target Language term mappings |

## Guidelines

1. **Use the standard/accepted term** in the target language's academic community
2. **Keep technical terms transliterated** if no native equivalent exists (e.g., "algorithm" → "অ্যালগরিদম" in Bengali)
3. **Do NOT translate proper nouns**: model names (GPT, BERT), dataset names, author names
4. **Add your name** to the `contributors` array
5. Start with at least **20 terms** per file

## Supported Domains

| Domain | File Name | Description |
|---|---|---|
| `cs` | `cs.json` | Computer science fundamentals |
| `ml` | `ml.json` | Machine learning & deep learning |
| `general_academic` | `general_academic.json` | Paper sections, research methods, publication terms |

Want to propose a new domain (e.g., `physics`, `biology`, `economics`)? Open an issue!

## Example: Adding Hindi Support

1. Create `glossaries/hi/general_academic.json`:

```json
{
    "domain": "general_academic",
    "language": "hi",
    "version": "1.0.0",
    "contributors": ["Your Name"],
    "terms": {
        "abstract": "सारांश",
        "introduction": "परिचय",
        "methodology": "कार्यप्रणाली"
    }
}
```

2. Submit a PR titled: `feat(glossary): add Hindi general academic terms`

That's it! 🎉
