/**
 * PeerTranslate — Frontend Application
 */

// ── State ──
let selectedFile = null;
let isTranslating = false;
let rawMarkdown = '';
let originalMarkdown = '';
let currentHashKey = null;
let totalSections = 0;
let completedSections = 0;
let sideBySideActive = false;

// ── DOM References ──
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const fileName = document.getElementById('file-name');
const fileSize = document.getElementById('file-size');
const fileRemoveBtn = document.getElementById('file-remove');
const inputTabs = document.querySelectorAll('.input-tab');
const tabContents = document.querySelectorAll('.tab-content');
const urlInput = document.getElementById('url-input');
const languageSelect = document.getElementById('language-select');
const translateBtn = document.getElementById('translate-btn');
const resultsSection = document.getElementById('results-section');
const statusLog = document.getElementById('status-log');
const verificationPanel = document.getElementById('verification-panel');
const overallScoreBadge = document.getElementById('overall-score');
const verificationGrid = document.getElementById('verification-grid');
const outputBody = document.getElementById('output-body');
const copyBtn = document.getElementById('copy-btn');
const downloadBtn = document.getElementById('download-btn');
const progressContainer = document.getElementById('progress-container');
const progressBarFill = document.getElementById('progress-bar-fill');
const progressLabel = document.getElementById('progress-label');
const cacheBadge = document.getElementById('cache-badge');
const sidebysideBtn = document.getElementById('sidebyside-btn');
const sidebysideContainer = document.getElementById('sidebyside-container');

// ── Initialize ──
document.addEventListener('DOMContentLoaded', () => {
    loadLanguages();
    setupDragDrop();
    setupEventListeners();
    setupDOIDetection();
});

// ── DOI Auto Detection + Unpaywall Resolution ──
function setupDOIDetection() {
    if (!urlInput) return;
    
    // Status element below URL input
    let doiStatus = document.getElementById('doi-status');
    if (!doiStatus) {
        doiStatus = document.createElement('div');
        doiStatus.id = 'doi-status';
        doiStatus.style.cssText = 'font-size:0.8rem;margin-top:0.5rem;color:var(--text-muted);display:none;';
        urlInput.parentNode.insertBefore(doiStatus, urlInput.nextSibling);
    }
    
    let doiTimeout = null;
    urlInput.addEventListener('input', () => {
        const val = urlInput.value.trim();
        clearTimeout(doiTimeout);
        
        // Detect bare DOI like 10.xxxx/...
        let doi = null;
        if (/^10\.\d{4,}\/.+/.test(val)) {
            doi = val;
        } else if (val.includes('doi.org/')) {
            const m = val.match(/doi\.org\/(10\..+)/);
            if (m) doi = m[1];
        }
        
        if (doi) {
            doiStatus.style.display = 'block';
            doiStatus.innerHTML = '⚡ DOI detected! Looking for open-access PDF via Unpaywall...';
            doiStatus.style.color = 'var(--accent-cyan)';
            
            doiTimeout = setTimeout(async () => {
                try {
                    const resp = await fetch(`/api/resolve-doi/${encodeURIComponent(doi)}`);
                    const data = await resp.json();
                    if (data.pdf_url) {
                        urlInput.value = data.pdf_url;
                        doiStatus.innerHTML = '✅ Open-access PDF found! URL updated automatically.';
                        doiStatus.style.color = '#22c55e';
                        validateSubmitButton();
                    } else {
                        doiStatus.innerHTML = `⚠️ ${data.error || 'No open-access PDF found. Please download manually and use Upload File tab.'}`;
                        doiStatus.style.color = 'var(--accent-amber)';
                    }
                } catch {
                    doiStatus.innerHTML = '⚠️ Could not resolve DOI. Please try the Upload File tab.';
                    doiStatus.style.color = 'var(--accent-rose)';
                }
            }, 800);
        } else {
            doiStatus.style.display = 'none';
        }
    });
}

// ── Load Available Languages ──
async function loadLanguages() {
    try {
        const response = await fetch('/api/languages');
        const data = await response.json();

        // 1. Add Default Placeholder
        const placeholder = document.createElement('option');
        placeholder.value = "";
        placeholder.textContent = "Select Target Language...";
        placeholder.disabled = true;
        placeholder.selected = true;
        languageSelect.appendChild(placeholder);

        // 2. Add API Languages
        data.languages.forEach((lang) => {
            const option = document.createElement('option');
            option.value = lang.code;
            option.textContent = lang.name;
            if (lang.has_glossary) {
                option.textContent += ' ✦';
            }
            languageSelect.appendChild(option);
        });

        // Revalidate form when user finally picks an option
        languageSelect.addEventListener('change', (e) => {
            validateSubmitButton();
        });

    } catch (error) {
        console.error('Failed to load languages:', error);
        // Fallback: add Bengali as default
        const option = document.createElement('option');
        option.value = 'bn';
        option.textContent = 'বাংলা (Bengali) ✦';
        option.selected = true;
        languageSelect.appendChild(option);
    }
}

// ── Drag & Drop Setup ──
function setupDragDrop() {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, preventDefaults);
        document.body.addEventListener(eventName, preventDefaults);
    });

    ['dragenter', 'dragover'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.add('drag-over');
        });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => {
            dropZone.classList.remove('drag-over');
        });
    });

    dropZone.addEventListener('drop', handleDrop);
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', handleFileSelect);
}

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

function handleDrop(e) {
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
}

function handleFileSelect(e) {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
}

function handleFile(file) {
    // Validate PDF
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        showNotification('Please select a PDF file.', 'error');
        return;
    }

    // Validate size (50MB max)
    if (file.size > 50 * 1024 * 1024) {
        showNotification('File too large. Maximum size is 50MB.', 'error');
        return;
    }

    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatFileSize(file.size);
    fileInfo.classList.add('visible');
    validateSubmitButton();
}

function removeFile() {
    selectedFile = null;
    fileInput.value = '';
    fileInfo.classList.remove('visible');
    validateSubmitButton();
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ── Event Listeners ──
function setupEventListeners() {
    // Hamburger Menu
    const hamburger = document.getElementById('nav-hamburger');
    const navLinks = document.getElementById('nav-links');
    const navbar = document.querySelector('.navbar');
    
    if (hamburger && navLinks) {
        hamburger.addEventListener('click', () => {
            navLinks.classList.toggle('mobile-open');
            if(navbar) navbar.classList.toggle('mobile-open');
        });
        
        // Close menu when clicking a link
        const links = navLinks.querySelectorAll('a');
        links.forEach(link => {
            link.addEventListener('click', () => {
                navLinks.classList.remove('mobile-open');
                if(navbar) navbar.classList.remove('mobile-open');
            });
        });
    }

    fileRemoveBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        removeFile();
    });

    // Tab switching
    inputTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            // Remove active class from all
            inputTabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // Add active class to clicked tab
            tab.classList.add('active');
            const target = tab.getAttribute('data-tab');
            document.getElementById(`tab-${target}`).classList.add('active');
            
            // Check submit button state
            validateSubmitButton();
        });
    });

    // URL input validation
    urlInput.addEventListener('input', validateSubmitButton);

    translateBtn.addEventListener('click', startTranslation);
    copyBtn.addEventListener('click', copyTranslation);
    downloadBtn.addEventListener('click', () => downloadMarkdownFile());

    // Side-by-side toggle
    if (sidebysideBtn) {
        sidebysideBtn.addEventListener('click', () => {
            sideBySideActive = !sideBySideActive;
            if (sideBySideActive) {
                sidebysideContainer.style.display = 'block';
                outputBody.style.display = 'none';
                sidebysideBtn.textContent = '📄 Single View';
                // populate side panels
                const sideTrans = document.getElementById('output-body-sidebyside');
                const sideOrig = document.getElementById('original-body');
                if (sideTrans && rawMarkdown) sideTrans.innerHTML = outputBody.innerHTML;
                if (sideOrig && originalMarkdown) {
                    sideOrig.innerHTML = typeof marked !== 'undefined' ? marked.parse(originalMarkdown) : `<pre>${originalMarkdown}</pre>`;
                } else if (sideOrig) {
                    sideOrig.innerHTML = '<p style="color:#999;text-align:center;margin-top:2rem;">Original English not available for this paper.</p>';
                }
            } else {
                sidebysideContainer.style.display = 'none';
                outputBody.style.display = 'block';
                sidebysideBtn.textContent = '📖 Side-by-Side';
            }
        });
    }

    // ToS checkbox gates the translate button
    const tosCheckbox = document.getElementById('tos-checkbox');
    if (tosCheckbox) {
        tosCheckbox.addEventListener('change', validateSubmitButton);
    }
    
    // Dynamic provider model options
    const providerSelect = document.getElementById('user-provider');
    const modelSelect = document.getElementById('user-model');
    const judgeProviderSelect = document.getElementById('judge-provider');
    const judgeModelSelect = document.getElementById('judge-model');
    const apiKeyLabel = document.getElementById('user-api-key-label');
    const apiKeyInput = document.getElementById('user-api-key');

    const fillModelOptions = (provider, selectElement) => {
        selectElement.innerHTML = '';
        if (provider === 'google') {
            selectElement.innerHTML = `
                <option value="">Default (Server Config — 500 RPD)</option>
                <option value="gemini-flash-lite-latest">Flash Lite Latest ⭐ (500 RPD)</option>
                <option value="gemini-2.0-flash">Gemini 2.0 Flash</option>
                <option value="gemini-2.5-flash-lite">Gemini 2.5 Flash Lite</option>
                <option value="gemini-3.0-flash">Gemini 3 Flash (20 RPD, 250K TPM)</option>
            `;
        } else if (provider === 'openrouter') {
            selectElement.innerHTML = `
                <option value="openrouter/free">Auto-Select Best Free Model</option>
                <option value="meta-llama/llama-3.3-70b-instruct:free">Llama 3.3 70B (Free)</option>
                <option value="google/gemma-2-27b-it:free">Gemma 2 27B (Free)</option>
                <option value="qwen/qwen3-coder:free">Qwen 3 Coder (Free)</option>
            `;
        } else if (provider === 'openai') {
            selectElement.innerHTML = `
                <option value="gpt-4o-mini">GPT-4o-Mini</option>
                <option value="gpt-4o">GPT-4o</option>
            `;
        }
    };
    
    providerSelect.addEventListener('change', (e) => {
        const provider = e.target.value;
        fillModelOptions(provider, modelSelect);
        
        if (provider === 'google') {
            apiKeyLabel.textContent = 'Custom API Key (Optional)';
            apiKeyInput.placeholder = 'Leave blank to use server key';
        } else {
            const name = provider === 'openrouter' ? 'OpenRouter' : 'OpenAI';
            apiKeyLabel.textContent = `${name} API Key (Required)`;
            apiKeyInput.placeholder = 'sk-...';
        }
        validateTranslatorConfig();
        validateJudgeConfig();
    });

    apiKeyInput.addEventListener('input', () => {
        validateTranslatorConfig();
        validateJudgeConfig();
    });

    judgeProviderSelect.addEventListener('change', (e) => {
        fillModelOptions(e.target.value, judgeModelSelect);
        validateJudgeConfig();
    });

    document.getElementById('judge-api-key').addEventListener('input', validateJudgeConfig);
}

function validateSubmitButton() {
    const activeTab = document.querySelector('.input-tab.active').getAttribute('data-tab');
    const tosChecked = document.getElementById('tos-checkbox')?.checked ?? false;
    const hasLanguage = languageSelect.value && languageSelect.value !== "";

    let hasInput = false;
    if (activeTab === 'file') {
        hasInput = !!selectedFile;
    } else if (activeTab === 'url') {
        hasInput = urlInput.value.trim().length > 0;
    }

    translateBtn.disabled = !(hasInput && tosChecked && hasLanguage);
}

// ── Translation Pipeline ──
async function startTranslation() {
    const activeTab = document.querySelector('.input-tab.active').getAttribute('data-tab');
    const isUrlMode = activeTab === 'url';

    if ((!selectedFile && !isUrlMode) || (isUrlMode && urlInput.value.trim() === '') || isTranslating) return;

    // --- Proactive Translator Validation ---
    const userProviderEl = document.getElementById('user-provider');
    const userApiKeyEl = document.getElementById('user-api-key');
    if (userProviderEl.value !== 'google' && userApiKeyEl.value.trim() === '') {
        alert(`❌ API Key Required\n\nYou selected ${userProviderEl.value.toUpperCase()} as your translator but didn't provide a key.\n\nPlease provide a key or switch to Google Gemini (Native).`);
        return;
    }

    // --- Proactive Judge Validation ---
    const judgeProviderEl = document.getElementById('judge-provider');
    const judgeApiKeyEl = document.getElementById('judge-api-key');

    const needsJudgeKey = judgeProviderEl.value !== 'google';
    const hasDirectKey = judgeApiKeyEl.value.trim() !== '';
    const canReuseKey = (judgeProviderEl.value === userProviderEl.value && userApiKeyEl.value.trim() !== '');

    if (needsJudgeKey && !hasDirectKey && !canReuseKey) {
        const confirmFallback = confirm(
            `⚠️ Judge Configuration Incomplete\n\nYou selected ${judgeProviderEl.value.toUpperCase()} as your judge but didn't provide an API key.\n\nWould you like to switch to the built-in Gemini Judge instead?`
        );
        if (confirmFallback) {
            judgeProviderEl.value = 'google';
            document.getElementById('judge-model').innerHTML = '<option value="">Default (Server Config)</option>';
            document.getElementById('judge-config-warning').style.display = 'none';
        } else {
            return; // Stop and let them fix it
        }
    }

    isTranslating = true;
    translateBtn.classList.add('loading');
    translateBtn.disabled = true;
    rawMarkdown = '';
    originalMarkdown = '';
    totalSections = 0;
    completedSections = 0;
    sideBySideActive = false;
    if (sidebysideContainer) sidebysideContainer.style.display = 'none';
    if (outputBody) outputBody.style.display = 'block';
    if (sidebysideBtn) { sidebysideBtn.style.display = 'none'; sidebysideBtn.textContent = '📖 Side-by-Side'; }
    if (cacheBadge) cacheBadge.style.display = 'none';
    if (progressContainer) progressContainer.style.display = 'block';
    if (progressBarFill) progressBarFill.style.width = '3%';
    if (progressLabel) progressLabel.textContent = 'Starting pipeline...';

    // Show results section
    resultsSection.classList.add('visible');
    statusLog.innerHTML = '';
    outputBody.innerHTML = '';
    verificationGrid.innerHTML = '';
    overallScoreBadge.textContent = '—';
    overallScoreBadge.className = 'score-badge';
    verificationPanel.classList.remove('visible');

    // Scroll to results
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Build form data
    const formData = new FormData();
    if (isUrlMode) {
        formData.append('url', urlInput.value.trim());
        // Append dummy file to satisfy FastAPI's multipart/form-data requirements
        formData.append('file', new Blob(['dummy'], {type: 'application/pdf'}), 'dummy.pdf');
    } else {
        formData.append('file', selectedFile);
    }
    formData.append('language', languageSelect.value);
    
    // Append BYOK & Settings
    const userProvider = document.getElementById('user-provider').value;
    const userModel = document.getElementById('user-model').value;
    const userApiKey = document.getElementById('user-api-key').value.trim();
    const judgeProvider = document.getElementById('judge-provider').value;
    const judgeModel = document.getElementById('judge-model').value;
    const judgeApiKey = document.getElementById('judge-api-key').value.trim();

    if (userProvider) formData.append('user_provider', userProvider);
    if (userModel) formData.append('user_model', userModel);
    if (userApiKey) formData.append('api_key', userApiKey);
    if (judgeProvider) formData.append('judge_provider', judgeProvider);
    if (judgeModel) formData.append('judge_model', judgeModel);
    if (judgeApiKey) formData.append('judge_api_key', judgeApiKey);

    // Append Quick Mode
    const quickMode = document.getElementById('quick-mode-checkbox');
    if (quickMode && quickMode.checked) {
        formData.append('quick_mode', 'true');
    }

    console.info('>>> SUBMITTING TRANSLATION:', {
        provider: userProvider,
        model: userModel,
        language: languageSelect.value,
        has_key: !!userApiKey
    });

    try {
        const response = await fetch('/api/translate', {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const text = await response.text();
            let errorMsg = `Server returned ${response.status}`;
            try {
                const errorData = JSON.parse(text);
                if (errorData && errorData.detail) {
                    errorMsg = typeof errorData.detail === 'string' 
                        ? errorData.detail 
                        : JSON.stringify(errorData.detail);
                }
            } catch (e) {
                errorMsg += `: ${text}`;
            }
            throw new Error(errorMsg);
        }

        // Read SSE stream
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            // Parse SSE events from buffer
            const lines = buffer.split('\n');
            buffer = lines.pop() || ''; // Keep incomplete line in buffer

            let eventType = '';
            let eventData = '';

            for (const rawLine of lines) {
                const line = rawLine.replace(/\r/g, '');
                if (line.startsWith('event:')) {
                    eventType = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                    const dataLine = line.slice(5).trim();
                    eventData = eventData ? eventData + '\n' + dataLine : dataLine;
                } else if (line.trim() === '' && eventType && eventData !== '') {
                    handleSSEEvent(eventType, eventData);
                    eventType = '';
                    eventData = '';
                }
            }
        }
    } catch (error) {
        console.error('Translation error:', error);
        
        // Show a clear, user-friendly error in the status log
        let userMessage = error.message;
        
        // Detect common publisher blocks and explain clearly
        if (userMessage.includes('403') || userMessage.includes('Forbidden')) {
            userMessage = '🔒 This publisher blocks automated downloads. Please download the PDF file manually to your computer, then click the "Upload File" tab to translate it.';
        } else if (userMessage.includes('HTML page') || userMessage.includes('not a PDF')) {
            userMessage = '📄 This URL points to a webpage, not a PDF file. Please find the direct PDF download link (usually ending in .pdf), or download the PDF and use the "Upload File" tab.';
        } else if (userMessage.includes('Failed to fetch') || userMessage.includes('NetworkError')) {
            userMessage = '🌐 Network error — Could not reach the server. Please check your internet connection and try again.';
        }
        
        addStatusEntry(`❌ Error: ${userMessage}`);
        
        // Also show in the output area so users don't miss it
        outputBody.innerHTML = `
            <div style="padding: 2rem; text-align: center;">
                <div style="font-size: 2rem; margin-bottom: 1rem;">⚠️</div>
                <div style="color: var(--accent-rose); font-weight: 600; margin-bottom: 0.5rem;">Translation Failed</div>
                <p style="color: var(--text-secondary); max-width: 500px; margin: 0 auto; line-height: 1.6;">${userMessage}</p>
            </div>
        `;
    } finally {
        isTranslating = false;
        translateBtn.classList.remove('loading');
        translateBtn.disabled = false;
    }
}

// ── SSE Event Handlers ──
function handleSSEEvent(type, rawData) {
    let data;
    try {
        data = JSON.parse(rawData);
    } catch (e) {
        data = rawData; // Fallback if somehow not JSON
    }

    switch (type) {
        case 'status':
            addStatusEntry(data);
            // Parse section count from status messages like "Translating section 3/21..."
            const sectionMatch = typeof data === 'string' && data.match(/(\d+)\/(\d+)/);
            if (sectionMatch) {
                completedSections = parseInt(sectionMatch[1]);
                totalSections = parseInt(sectionMatch[2]);
                const pct = Math.min(95, Math.round((completedSections / totalSections) * 90) + 5);
                if (progressBarFill) progressBarFill.style.width = `${pct}%`;
                if (progressLabel) progressLabel.textContent = `Section ${completedSections}/${totalSections}`;
            }
            break;

        case 'cache_info':
            if (data && data.hash_key) currentHashKey = data.hash_key;
            // Show cache badge if this was a cache hit
            if (data && data.from_cache && cacheBadge) {
                cacheBadge.style.display = 'block';
                if (progressContainer) progressContainer.style.display = 'none';
            }
            break;


        case 'original_english':
            originalMarkdown = data;
            break;

        case 'translation':
            renderTranslation(data);
            break;

        case 'verification':
            if (typeof data === 'object') renderVerification(data);
            break;

        case 'verification_section':
            if (typeof data === 'object') renderSectionVerification(data);
            break;

        case 'retranslation':
            if (data && data.section) addStatusEntry(`🔧 Re-translated: ${data.section}`);
            break;

        case 'error':
            addStatusEntry(`❌ ${data}`);
            break;

        case 'warning':
            addStatusEntry(`⚠️ ${data}`);
            break;

        case 'complete':
            addStatusEntry(`🎉 ${data}`);
            if (progressBarFill) progressBarFill.style.width = '100%';
            if (progressLabel) progressLabel.textContent = 'Complete!';
            setTimeout(() => { if (progressContainer) progressContainer.style.display = 'none'; }, 2000);
            showDownloadActions();
            if (sidebysideBtn) sidebysideBtn.style.display = 'inline-flex';
            break;
    }
}

// ── Status Log ──
function addStatusEntry(text) {
    const entry = document.createElement('div');
    entry.className = 'status-entry';
    entry.textContent = text;
    statusLog.appendChild(entry);
    statusLog.scrollTop = statusLog.scrollHeight;
}

// ── Render Translation ──
// Sentinel used to detect and skip the initial loading placeholder
const LOADING_SENTINEL = '⏳';
function renderTranslation(markdownText) {
    // If this is just the loading placeholder, show it softly
    // but don't overwrite a real translation that's already displayed
    const isLoadingPlaceholder = markdownText.includes(LOADING_SENTINEL) &&
        markdownText.includes('Translation in Progress');
    if (isLoadingPlaceholder && rawMarkdown && rawMarkdown.length > 200) {
        return; // already have real content
    }
    rawMarkdown = markdownText;
    outputBody.dataset.rawMarkdown = markdownText;
    if (typeof marked !== 'undefined') {
        outputBody.innerHTML = marked.parse(markdownText);
    } else {
        outputBody.innerHTML = basicMarkdownRender(markdownText);
    }
}

function basicMarkdownRender(text) {
    // Very basic Markdown to HTML conversion as a fallback
    let html = text
        // Headers
        .replace(/^### (.*$)/gm, '<h3>$1</h3>')
        .replace(/^## (.*$)/gm, '<h2>$1</h2>')
        .replace(/^# (.*$)/gm, '<h1>$1</h1>')
        // Bold and italic
        .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // Code
        .replace(/`(.*?)`/g, '<code>$1</code>')
        // Line breaks
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');

    return '<p>' + html + '</p>';
}

// ── Render Verification Report ──
function renderVerification(report) {
    verificationPanel.classList.add('visible');

    // Update overall score badge with final numbers
    overallScoreBadge.textContent = `${report.overall_score}% — ${formatLabel(report.overall_label)}`;
    overallScoreBadge.className = `score-badge ${report.overall_label}`;

    // Only rebuild section cards if the backend provided them.
    // If section_scores is empty, individual cards were already rendered
    // incrementally via verification_section events — DO NOT wipe the grid.
    if (report.sections && report.sections.length > 0) {
        verificationGrid.innerHTML = '';
        report.sections.forEach((section) => {
            appendVerificationCard(section);
        });
    }
    // If grid is still empty (edge case), show a mild indicator
    if (verificationGrid.children.length === 0) {
        verificationGrid.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem;">Sections verified in real-time above.</div>';
    }
}

function renderSectionVerification(sectionData) {
    verificationPanel.classList.add('visible');
    
    // Incrementally update overall accuracy badge
    const metrics = sectionData.metrics;
    overallScoreBadge.textContent = `${metrics.running_avg}% — [Section ${metrics.current_index}/${metrics.total_sections}]`;
    
    // Style badge based on final average if complete, or current if ongoing
    const label = getLabelForScore(metrics.running_avg);
    overallScoreBadge.className = `score-badge ${label}`;

    // Append the new card
    appendVerificationCard(sectionData);
}

function appendVerificationCard(section) {
    const card = document.createElement('div');
    card.className = `section-card ${section.label}`;
    card.innerHTML = `
        <div class="section-card-title" title="${escapeHtml(section.title)}">${escapeHtml(section.title)}</div>
        <div class="section-card-score">${section.score}% confidence</div>
    `;
    verificationGrid.appendChild(card);
    verificationGrid.scrollTop = verificationGrid.scrollHeight;
}

function getLabelForScore(score) {
    if (score >= 95) return 'excellent';
    if (score >= 85) return 'good';
    if (score >= 70) return 'needs_review';
    return 'low_confidence';
}

function formatLabel(label) {
    const labels = {
        excellent: 'Excellent',
        good: 'Good',
        needs_review: 'Needs Review',
        low_confidence: 'Low Confidence',
        skipped: 'Skipped',
    };
    return labels[label] || label;
}

// ── Copy ──
function copyTranslation() {
    const md = rawMarkdown || outputBody.dataset.rawMarkdown;
    if (!md) { showNotification('No translation to copy.', 'error'); return; }
    navigator.clipboard.writeText(md)
        .then(() => {
            showNotification('Copied to clipboard!', 'success');
            copyBtn.textContent = '✓ Copied';
            setTimeout(() => { copyBtn.innerHTML = '📋 Copy'; }, 2000);
        })
        .catch(() => showNotification('Failed to copy.', 'error'));
}

// ── Download as Markdown ──
function downloadMarkdownFile() {
    const md = rawMarkdown || outputBody.dataset.rawMarkdown;
    if (!md) { showNotification('No translation to download.', 'error'); return; }
    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `peertranslate_${languageSelect.value || 'translation'}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showNotification('Downloaded!', 'success');
}

// ── Download as PDF (printer dialog) ──
function downloadAsPDF() {
    window.print();
}

// ── Download as DOCX ──
async function downloadDocx() {
    const md = rawMarkdown || outputBody.dataset.rawMarkdown;
    if (!md) { showNotification('No translation to export.', 'error'); return; }
    try {
        const resp = await fetch('/api/export/docx', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ markdown: md, filename: `peertranslate_${languageSelect.value || 'translation'}` })
        });
        if (!resp.ok) throw new Error('Export failed');
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `peertranslate_${languageSelect.value || 'translation'}.docx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showNotification('DOCX downloaded!', 'success');
    } catch (e) {
        showNotification('DOCX export failed.', 'error');
    }
}

// ── Download as LaTeX ──
async function downloadLatex() {
    const md = rawMarkdown || outputBody.dataset.rawMarkdown;
    if (!md) { showNotification('No translation to export.', 'error'); return; }
    try {
        const resp = await fetch('/api/export/latex', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ markdown: md, filename: `peertranslate_${languageSelect.value || 'translation'}` })
        });
        if (!resp.ok) throw new Error('Export failed');
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `peertranslate_${languageSelect.value || 'translation'}.tex`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showNotification('LaTeX downloaded!', 'success');
    } catch (e) {
        showNotification('LaTeX export failed.', 'error');
    }
}

// Keep old name for backward compat
function downloadTranslation() { downloadMarkdownFile(); }

// ── Notification ──
function showNotification(message, type = 'info') {
    // Simple console notification — can be enhanced with toast UI
    console.log(`[${type.toUpperCase()}] ${message}`);
}

// ── Utility ──
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Download as PDF ──
document.getElementById('download-pdf-btn')?.addEventListener('click', () => downloadAsPDF());
// ── Download as DOCX ──
document.getElementById('download-docx-btn')?.addEventListener('click', () => downloadDocx());
// ── Download as LaTeX ──
document.getElementById('download-latex-btn')?.addEventListener('click', () => downloadLatex());
// ── Download as Markdown ──
document.getElementById('download-md-btn')?.addEventListener('click', () => downloadMarkdownFile());
// ── Copy Full Translation ──
document.getElementById('copy-full-btn')?.addEventListener('click', () => {
    const md = rawMarkdown || outputBody.dataset.rawMarkdown;
    if (md) navigator.clipboard.writeText(md).then(() => showNotification('Copied!', 'success'));
});

// ── Flag Translation Error ──
document.getElementById('flag-translation-btn')?.addEventListener('click', () => {
    const reason = prompt(
        '🚩 Report Translation Error\n\n' +
        'Please describe what is wrong with this translation:\n' +
        '(e.g., "Section 3 contains fabricated content", "Abstract is duplicated")'
    );
    if (reason && reason.trim()) {
        // Send flag to server
        fetch('/api/flag', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                hash_key: currentHashKey,
                reason: reason.trim(),
                language: languageSelect.value,
                timestamp: new Date().toISOString()
            })
        }).then(r => {
            if (r.ok) {
                alert('✅ Thank you! Your report has been submitted.\n\nOur community reviewers will investigate this translation.');
            } else {
                alert('⚠️ Could not submit the report. Please try again later.');
            }
        }).catch(() => {
            alert('⚠️ Network error. The report could not be sent.');
        });
    }
});

// ── Show download actions when translation is complete ──
function showDownloadActions() {
    const el = document.getElementById('download-actions');
    if (el) el.style.display = 'flex';
}
