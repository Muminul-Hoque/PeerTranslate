/**
 * PeerTranslate — Frontend Application
 *
 * Handles drag-and-drop PDF upload, SSE streaming of translation,
 * Markdown rendering, and verification score visualization.
 */

// ── State ──
let selectedFile = null;
let isTranslating = false;
let eventSource = null;
let rawMarkdown = '';
let isGenerating = false;
let currentHashKey = null;

// ── DOM References ──
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const fileInfo = document.getElementById('file-info');
const fileName = document.getElementById('file-name');
const fileSize = document.getElementById('file-size');
const fileRemoveBtn = document.getElementById('file-remove');

// New URL and Tabs references
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

// ── Initialize ──
document.addEventListener('DOMContentLoaded', () => {
    loadLanguages();
    setupDragDrop();
    setupEventListeners();
});

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
    downloadBtn.addEventListener('click', downloadTranslation);

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
                <option value="">Default (Server Config)</option>
                <option value="gemma-3-27b-it">Gemma 3 27B ⭐ (14,400 RPD - Best Free Quota)</option>
                <option value="gemma-4-26b-it">Gemma 4 26B (1,500 RPD, Unlimited TPM)</option>
                <option value="gemma-4-31b-it">Gemma 4 31B (1,500 RPD, Unlimited TPM)</option>
                <option value="gemini-2.5-flash">Gemini 2.5 Flash (250K TPM)</option>
                <option value="gemini-1.5-pro">Gemini 1.5 Pro</option>
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
            let errorData;
            try {
                errorData = await response.json();
            } catch (e) {
                const text = await response.text();
                throw new Error(`Server returned ${response.status}: ${text}`);
            }
            
            let errorMsg = 'Translation request failed.';
            if (errorData && errorData.detail) {
                if (typeof errorData.detail === 'string') {
                    errorMsg = errorData.detail;
                } else {
                    // FastAPI validation errors are arrays of objects
                    errorMsg = JSON.stringify(errorData.detail);
                }
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
        addStatusEntry(`❌ Error: ${error.message}`);
        console.error('Translation error:', error);
    } finally {
        isTranslating = false;
        translateBtn.classList.remove('loading');
        translateBtn.disabled = false;
    }
}

// ── SSE Event Handlers ──
function handleSSEEvent(type, data) {
    switch (type) {
        case 'status':
            addStatusEntry(data);
            break;

        case 'cache_info':
            try {
                const info = JSON.parse(data);
                if (info.hash_key) currentHashKey = info.hash_key;
            } catch {
                console.warn('Failed to parse cache info');
            }
            break;

        case 'translation':
            renderTranslation(data);
            break;

        case 'verification':
            try {
                const report = JSON.parse(data);
                renderVerification(report);
            } catch {
                console.warn('Failed to parse verification data');
            }
            break;

        case 'verification_section':
            try {
                const sectionData = JSON.parse(data);
                renderSectionVerification(sectionData);
            } catch {
                console.warn('Failed to parse section verification data');
            }
            break;

        case 'retranslation':
            try {
                const section = JSON.parse(data);
                addStatusEntry(`🔧 Re-translated: ${section.section}`);
            } catch {
                console.warn('Failed to parse retranslation data');
            }
            break;

        case 'error':
            addStatusEntry(`❌ ${data}`);
            break;

        case 'warning':
            addStatusEntry(`⚠️ ${data}`);
            break;

        case 'complete':
            addStatusEntry(`🎉 ${data}`);
            showDownloadActions();
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
function renderTranslation(markdownText) {
    // Use marked.js for Markdown rendering
    if (typeof marked !== 'undefined') {
        outputBody.innerHTML = marked.parse(markdownText);
    } else {
        // Fallback: basic Markdown rendering
        outputBody.innerHTML = basicMarkdownRender(markdownText);
    }

    // Store raw markdown for copy/download
    outputBody.dataset.rawMarkdown = markdownText;
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

    // Overall score badge
    overallScoreBadge.textContent = `${report.overall_score}% — ${formatLabel(report.overall_label)}`;
    overallScoreBadge.className = `score-badge ${report.overall_label}`;

    // Section cards
    verificationGrid.innerHTML = '';

    if (report.sections && report.sections.length > 0) {
        report.sections.forEach((section) => {
            appendVerificationCard(section);
        });
    } else {
        verificationGrid.innerHTML = '<div style="color: var(--text-muted); font-size: 0.9rem;">No sections to verify.</div>';
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

// ── Copy & Download ──
function copyTranslation() {
    const rawMarkdown = outputBody.dataset.rawMarkdown;
    if (!rawMarkdown) {
        showNotification('No translation to copy.', 'error');
        return;
    }

    navigator.clipboard
        .writeText(rawMarkdown)
        .then(() => {
            showNotification('Copied to clipboard!', 'success');
            copyBtn.textContent = '✓ Copied';
            setTimeout(() => {
                copyBtn.innerHTML = '📋 Copy';
            }, 2000);
        })
        .catch(() => {
            showNotification('Failed to copy.', 'error');
        });
}

function downloadTranslation() {
    const rawMarkdown = outputBody.dataset.rawMarkdown;
    if (!rawMarkdown) {
        showNotification('No translation to download.', 'error');
        return;
    }

    const blob = new Blob([rawMarkdown], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `translated_${languageSelect.value}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showNotification('Downloaded!', 'success');
}

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

// ── Download as PDF (Print) ──
document.getElementById('download-pdf-btn')?.addEventListener('click', () => {
    window.print();
});

// ── Download as Markdown (new button) ──
document.getElementById('download-md-btn')?.addEventListener('click', () => {
    downloadMarkdown();
});

// ── Copy Full Translation ──
document.getElementById('copy-full-btn')?.addEventListener('click', () => {
    if (rawMarkdown) {
        navigator.clipboard.writeText(rawMarkdown).then(() => {
            showNotification('Copied to clipboard!', 'success');
        });
    }
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
