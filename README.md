<div align="center">

# 📄 PeerTranslate

### Translate Research Papers into Your Own Language — With Verified Accuracy

[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Powered by Gemini](https://img.shields.io/badge/AI-Google%20Gemini-orange?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev/)
[![Contributions Welcome](https://img.shields.io/badge/Contributions-Welcome-brightgreen?style=flat-square)](CONTRIBUTING.md)

**The first open-source AI translation tool with back-translation verification and community-curated academic glossaries.**

[🚀 Quick Start](#-quick-start) · [🔬 How It Works](#-how-it-works) · [🌍 Add Your Language](#-add-your-language) · [🤝 Contributing](#-contributing)

</div>

---

## 🎯 The Problem

Millions of researchers worldwide struggle to read English-language papers in their native language. Existing translation tools:
- ❌ Break formatting, equations, and tables
- ❌ Mistranslate academic jargon ("attention mechanism" → literal translation)
- ❌ Provide **no way to verify** if the translation is accurate
- ❌ Ignore low-resource languages like Bengali, Tamil, Swahili

## ✅ Our Solution

PeerTranslate uses a **4-pass Verify Loop** to deliver accurate, verified translations:

```
📄 Upload PDF → 🔄 Translate with Glossary → 🔁 Back-Translate → 🔍 Score & Verify → ✅ Result
```

| Feature | PeerTranslate | Others |
|---|---|---|
| Multi-pass verification | ✅ Back-translation scoring | ❌ Single pass |
| Domain glossaries | ✅ Community-curated, term-locked | ❌ Generic translation |
| Accuracy scoring | ✅ Per-section confidence scores | ❌ No measurement |
| Low-resource languages | ✅ Bengali-first, any language welcome | ❌ Poor support |
| Open source | ✅ MIT License | ⚠️ Varies |

---

## 🔬 How It Works

PeerTranslate runs a **4-pass pipeline** on every paper:

| Pass | What Happens |
|---|---|
| **Pass 1** 📄 | Translate the full paper using Gemini AI + domain-specific glossary term-locking |
| **Pass 2** 🔁 | Back-translate the result to English |
| **Pass 3** 🔍 | Compare original ↔ back-translation, compute per-section similarity scores |
| **Pass 4** ✅ | Re-translate any section that falls below the confidence threshold |

The result: a translated paper with a **verification report** showing confidence scores for each section.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- A free [Google Gemini API key](https://aistudio.google.com/apikey)

### Installation

```bash
# Clone the repository
git clone https://github.com/muminul-hoque/PeerTranslate.git
cd PeerTranslate

# Install dependencies
pip install -r requirements.txt

# Configure your API key
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### Run

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser. Drop a PDF and translate! 🎉

---

## 🌍 Add Your Language

PeerTranslate ships with **Bengali** glossaries. We need YOUR help to add more languages!

**Currently supported (with glossaries):**
- 🇧🇩 Bengali (বাংলা) — 170+ curated terms

**Supported (without glossaries yet — contribute!):**
- 🇮🇳 Hindi, Tamil · 🇵🇰 Urdu · 🇪🇸 Spanish · 🇫🇷 French · 🇩🇪 German
- 🇯🇵 Japanese · 🇰🇷 Korean · 🇨🇳 Chinese · 🇸🇦 Arabic · 🇧🇷 Portuguese
- 🇷🇺 Russian · 🇰🇪 Swahili · 🇹🇷 Turkish

### How to contribute a glossary:

1. Fork this repo
2. Create `glossaries/{your_language_code}/general_academic.json`
3. Add 20+ terms following the [glossary format](glossaries/README.md)
4. Submit a Pull Request!

See [glossaries/README.md](glossaries/README.md) for the full guide.

---

## 📁 Project Structure

```
PeerTranslate/
├── backend/                   # FastAPI backend
│   ├── main.py               # API routes & SSE streaming
│   ├── translator.py         # 4-pass translation pipeline
│   ├── verifier.py           # Back-translation verification
│   ├── glossary.py           # Glossary loading & term-locking
│   └── config.py             # Settings & environment variables
├── frontend/                  # Vanilla HTML/CSS/JS frontend
│   ├── index.html            # Main page
│   ├── css/style.css         # Premium dark glassmorphic UI
│   └── js/app.js             # Upload, SSE streaming, rendering
├── glossaries/                # Community-curated term dictionaries
│   ├── bn/                   # Bengali (170+ terms)
│   │   ├── cs.json           # Computer Science
│   │   ├── ml.json           # Machine Learning
│   │   └── general_academic.json
│   └── README.md             # Glossary contribution guide
├── .env.example              # API key template
├── requirements.txt          # Python dependencies
├── Dockerfile                # Docker deployment
├── CITATION.cff              # Academic citation metadata
├── CONTRIBUTING.md           # Contributor guide
├── CODE_OF_CONDUCT.md        # Community standards
└── LICENSE                   # MIT License
```

---

## 🤝 Contributing

We welcome contributions from researchers, translators, and developers worldwide!

- **🌍 Add a language**: Contribute glossaries in your native language
- **🔧 Improve translation**: Enhance prompts, add new domains
- **🎨 Improve UI**: Make the frontend even more beautiful
- **🐛 Report bugs**: Open an issue if something breaks
- **📖 Improve docs**: Help make the project more accessible

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📖 Citation

If PeerTranslate helps your research, please cite it:

```bibtex
@software{peertranslate_2026,
    title        = {PeerTranslate: Verified Research Paper Translation for Every Language},
    author       = {Muhammed Muminul Hoque},
    year         = {2026},
    url          = {https://github.com/muminul-hoque/PeerTranslate},
    license      = {MIT}
}
```

---

## 📜 License

This project is licensed under the [MIT License](LICENSE).

---

<div align="center">

**Made with ❤️ for researchers who deserve knowledge in their own language.**

[⭐ Star this repo](https://github.com/muminul-hoque/PeerTranslate) if you find it useful!

</div>
