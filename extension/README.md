# PeerTranslate Chrome Extension

A lightweight Chrome extension that adds a floating "Translate with PeerTranslate" button on supported academic paper websites.

## Supported Sites
- ✅ ArXiv (`arxiv.org/abs/*` and `arxiv.org/pdf/*`)
- ✅ PubMed (`pubmed.ncbi.nlm.nih.gov/*`)
- ✅ bioRxiv (`biorxiv.org/content/*`)
- ✅ DOI links (`doi.org/*`)

## Installation (Developer Mode)

1. Open Chrome and navigate to `chrome://extensions/`
2. Enable **Developer mode** (toggle in top right)
3. Click **Load unpacked**
4. Select the `extension/` directory from this repository
5. Visit any ArXiv paper page — you'll see a floating cyan button

## How It Works

When you visit a supported paper page, the extension:
1. Detects the paper type (ArXiv, PubMed, bioRxiv, DOI)
2. Extracts the direct PDF URL
3. Injects a floating button that opens PeerTranslate with the PDF pre-loaded

## Note
You'll need to generate icon files (`icon48.png` and `icon128.png`) for the extension.
A simple way: use any favicon generator or create a 48x48 and 128x128 PNG with the 📄 emoji.
