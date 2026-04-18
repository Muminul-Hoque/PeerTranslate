# Contributing to PeerTranslate

Thank you for your interest in contributing! Every contribution — from fixing a typo to adding an entire language — helps researchers worldwide access academic knowledge in their native language.

## 🌍 Ways to Contribute

### 1. Add a Language Glossary (Easiest!)

**No coding required.** If you are a native speaker of any language (e.g., a biology professor from Bangladesh, a physics student from Spain), you can help by adding academic term translations.

#### Option A: The Web Editor (Recommended for Non-Coders)
1. Run the app or visit the hosted version.
2. Go to the `/contribute` page.
3. Type in English terms and their translations in your language.
4. Click Submit! (This will safely draft a GitHub issue for our team to review).

#### Option B: For Developers (Via Git)
1. Fork this repository
2. Create a new folder: `glossaries/{language_code}/` (e.g., `glossaries/hi/` for Hindi)
3. Add a JSON file following the [glossary format](glossaries/README.md)
4. Submit a Pull Request with the title: `feat(glossary): add {Language} {domain} terms`

**Minimum**: 20 terms per file.

### 2. Improve Translation Quality

- Enhance prompts in `backend/translator.py`
- Add domain-specific instructions for better accuracy
- Improve the verification scoring logic in `backend/verifier.py`

### 3. Improve the Frontend

- Enhance CSS animations and responsiveness
- Add dark/light theme toggle
- Improve mobile UX
- Add accessibility features

### 4. Report Issues

- Bug reports: Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md)
- Feature requests: Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md)
- Glossary issues: Use the [Glossary Contribution template](.github/ISSUE_TEMPLATE/glossary_contribution.md)

---

## 🛠 Development Setup

```bash
# Clone your fork
git clone https://github.com/YOUR_USERNAME/PeerTranslate.git
cd PeerTranslate

# Create virtual environment
python -m venv venv
venv\Scripts\activate    # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Run the dev server
python -m uvicorn backend.main:app --reload --port 8000
```

---

## 📝 Code Style

- **Python**: Follow PEP 8. Use type hints for all function signatures.
- **Imports**: Standard library → Third-party → Local modules
- **Docstrings**: Google-style docstrings for all public functions
- **File length**: Keep files under 400 lines; split if exceeding
- **Logging**: Use `logging.getLogger(__name__)`, never `print()`

---

## 🔀 Pull Request Process

1. **Fork** the repository
2. Create a **feature branch**: `git checkout -b feat/your-feature`
3. Make your changes
4. **Test** your changes locally
5. **Commit** with a descriptive message: `feat: add Hindi ML glossary`
6. **Push** your branch: `git push origin feat/your-feature`
7. Open a **Pull Request** against `main`

### Commit Convention

```
feat: add new feature
fix: fix a bug
docs: update documentation
glossary: add/update glossary terms
style: CSS/formatting changes
refactor: code refactoring
test: add or update tests
```

---

## 🤝 Code of Conduct

Please be respectful and inclusive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## ❓ Questions?

Open a [Discussion](https://github.com/muminul-hoque/PeerTranslate/discussions) or reach out via Issues. We are happy to help!
