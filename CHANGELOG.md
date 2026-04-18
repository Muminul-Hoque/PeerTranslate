# Changelog

All notable changes to PeerTranslate will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-18

### Added
- **AI-Judge Semantic Verification**: Replaced literal character matching with an AI-powered semantic evaluator for accuracy scoring
- **Selectable Verification Judge**: Choose between Google Gemini, OpenAI, or OpenRouter as your verification judge
- **Dual-Key System**: Separate API keys for translator and judge, enabling cross-provider verification
- **Proactive Configuration Validation**: Real-time warnings and pre-flight checks for missing API keys
- **Transparent Resilient Fallback**: Triple-layer safety net (Custom Judge → Server Gemini → Literal Math) with explicit user warnings
- **Strict Integrity Mode**: Anti-hallucination guards across extraction, translation, judging, and refinement prompts
- **Structural De-duplication**: Automatic detection and removal of duplicate sections (e.g., double abstracts)
- **PDF Export**: Print-optimized CSS for one-click PDF download
- **Flag Translation Error**: Community reporting system for incorrect translations
- **96% Accuracy Threshold**: Raised from 85% to ensure higher quality output

### Fixed
- False-low accuracy scores caused by literal character matching penalizing synonyms
- Fabricated sections appearing after the bibliography
- Duplicate abstracts from cover page and body text
- 404 error with deprecated `gemini-1.5-flash-latest` model name

## [0.1.0] - 2026-04-17

### Added
- Initial release
- 4-pass translation pipeline (Translate → Back-Translate → Score → Refine)
- Community-curated glossary system with Bengali (170+ terms)
- Real-time SSE streaming with live status updates
- URL-based and file-upload translation modes
- Multi-provider support (Google Gemini, OpenAI, OpenRouter)
- Premium dark glassmorphic UI
- Docker deployment support
- GitHub CI/CD with glossary validation
- Academic citation metadata (CITATION.cff)
