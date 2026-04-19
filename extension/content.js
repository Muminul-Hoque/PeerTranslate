/**
 * PeerTranslate Chrome Extension — Content Script
 *
 * Injects a floating "Translate this paper" button on supported
 * academic paper pages (ArXiv, PubMed, bioRxiv).
 */

(function () {
  'use strict';

  const PEERTRANSLATE_URL = 'https://peertranslate.onrender.com';

  // Determine the PDF URL based on the current page
  function getPdfUrl() {
    const href = window.location.href;

    // ArXiv: /abs/2307.03172 → /pdf/2307.03172.pdf
    if (href.includes('arxiv.org/abs/')) {
      return href.replace('/abs/', '/pdf/') + '.pdf';
    }
    if (href.includes('arxiv.org/pdf/')) {
      return href.endsWith('.pdf') ? href : href + '.pdf';
    }

    // bioRxiv: /content/10.1101/... → same + .full.pdf
    if (href.includes('biorxiv.org/content/')) {
      return href.replace(/\/content\//, '/content/') + '.full.pdf';
    }

    // PubMed: link to the PMC full-text PDF if available
    const pmcLink = document.querySelector('a[data-ga-action="PMC"]');
    if (pmcLink) {
      return pmcLink.href + '/pdf/';
    }

    // doi.org: pass the DOI itself — our backend will resolve it via Unpaywall
    if (href.includes('doi.org/')) {
      return href;
    }

    return null;
  }

  // Create the floating button
  function injectButton() {
    const pdfUrl = getPdfUrl();
    if (!pdfUrl) return;

    const btn = document.createElement('a');
    btn.id = 'peertranslate-ext-btn';
    btn.href = `${PEERTRANSLATE_URL}?url=${encodeURIComponent(pdfUrl)}`;
    btn.target = '_blank';
    btn.rel = 'noopener noreferrer';
    btn.innerHTML = '📄 Translate with PeerTranslate';
    btn.title = 'Open this paper in PeerTranslate for instant translation';

    document.body.appendChild(btn);
  }

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectButton);
  } else {
    injectButton();
  }
})();
