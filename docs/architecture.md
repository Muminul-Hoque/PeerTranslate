# System Architecture

PeerTranslate uses a highly modular, decoupled architecture consisting of a FastAPI backend and a Vanilla JS frontend, communicating via HTTP APIs and Server-Sent Events (SSE) for real-time streaming.

## High-Level Architecture

```mermaid
flowchart TD
    %% Frontend Layer
    subgraph Frontend [Browser Layer (Vanilla JS + CSS)]
        UI[User Interface]
        SSE_Handler[SSE Stream Handler]
        PDF_Engine[Render Engine (Markdown)]
    end

    %% API Gateway Layer
    subgraph Gateway [FastAPI Server]
        API_Route["POST /api/translate"]
        Flag_Route["POST /api/flag"]
    end

    %% Backend Services Layer
    subgraph Backend [Translation Core]
        Cache[(SQLite Community Cache)]
        Extractor[PDF Structural Extractor]
        Pipe_T[Pass 1: Translator]
        Pipe_BT[Pass 2: Back-Translator]
        Pipe_V[Pass 3: Semantic Judge]
        Pipe_R[Pass 4: Error Corrector]
    end

    %% External Services
    subgraph External [AI Providers]
        GenAI[Google Gemini API]
        OpenAI[OpenAI API]
        OpenRouter[OpenRouter API]
    end

    %% Connections
    UI -- "1. Upload PDF" --> API_Route
    API_Route -- "2. Check" --> Cache
    Cache -- "Hit: Return data" --> SSE_Handler
    
    Cache -- "Miss: Start Pipeline" --> Extractor
    Extractor -- "PDF Bytes" --> GenAI
    GenAI -- "English Markdown" --> Pipe_T
    
    Pipe_T --> Pipe_BT --> Pipe_V
    Pipe_V -- "Score < 96%" --> Pipe_R
    Pipe_R --> Pipe_V
    Pipe_V -- "Score >= 96%" --> Cache
    
    Pipe_T -.-> External
    Pipe_BT -.-> External
    Pipe_V -.-> External
    Pipe_R -.-> External
    
    API_Route -- "SSE Stream" --> SSE_Handler
    SSE_Handler --> PDF_Engine
```

## The 4-Pass Verification Pipeline

PeerTranslate solves the "black box" problem of AI translation by forcing the AI to prove its work.

1. **Pass 1 (Translation)**: The source English markdown is translated piece-by-piece using the user's selected provider.
2. **Pass 2 (Back-Translation)**: The target language output is translated *back* into English by a fresh model context.
3. **Pass 3 (Semantic Judge)**: An AI judge compares the original English with the back-translated English to verify semantic fidelity.
4. **Pass 4 (Refinement)**: If the Judge scores the translation <96%, the section is forwarded to an Error Correction agent that explicitly fixes the hallucinated or dropped concepts.

## Community Cache & Flagging

To avoid wasting API credits on papers that have already been accurately translated:

1. A SHA-256 hash is generated from `[PDF bytes] + [Target Language]`.
2. The SQLite database checks for this hash.
3. If found and its score is >= 80%, the cached translation is served instantly.
4. Users can click "🚩 Flag Translation" on the frontend if they spot an error.
5. If an entry reaches 3 flags, it is "quarantined" and the next user will trigger a fresh translation.

## Glossary Engine

The glossary engine guarantees that highly specific academic terms are translated consistently.
- Stored as standard JSON in `/glossaries/{lang}/`.
- Handled at startup by `get_available_glossaries()`.
- Injected into the system prompt of Pass 1 and Pass 4 to anchor the AI's vocabulary.
