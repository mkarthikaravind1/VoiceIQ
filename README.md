# VoiceIQ 🎙️

> **Real-time voice AI customer service agent** — browser-based, low-latency, with barge-in interruption, sentiment-based escalation, multilingual support, and RAG-powered FAQ retrieval.

---

## 📌 Project Overview

VoiceIQ is a full-stack real-time voice agent built for customer service automation. The user speaks into their browser; VoiceIQ transcribes the speech, runs it through an AI agent, and responds with synthesized voice — all within the same WebSocket connection, with no page reloads.

Key differentiators over a basic chatbot:
- **Barge-in**: User can interrupt the agent mid-speech
- **Sentiment escalation**: Detects frustrated users and auto-escalates to human support
- **RAG/FAQ retrieval**: Grounds responses in a knowledge base using vector search
- **Multi-turn memory**: Maintains conversation context across the entire session
- **Entity highlighting**: Frontend highlights key entities (order IDs, dates) in real time

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎤 Real-time STT | Faster-Whisper transcribes mic audio with language detection |
| 🔊 Streaming TTS | Piper synthesizes audio chunk-by-chunk for low perceived latency |
| ⚡ Barge-in | User can interrupt agent speech; TTS task is cancelled instantly |
| 😠 Sentiment Escalation | Two consecutive turns below -0.5 sentiment triggers human handoff |
| 🔍 RAG / FAQ Retrieval | ChromaDB + SentenceTransformers retrieves relevant knowledge base docs |
| 🧠 Multi-turn Memory | Full conversation history injected into every LangGraph agent turn |
| 🏷️ Entity Highlighting | Frontend regex highlights names, IDs, dates in transcripts |
| 📋 Session Summary | LangGraph terminal node generates a structured summary on session end |
| 🌐 Multilingual | Faster-Whisper auto-detects language; pipeline handles multiple languages |

---

## 🛠️ Tech Stack

### Backend
| Layer | Technology |
|---|---|
| API & WebSocket | FastAPI + Uvicorn |
| Speech-to-Text | Faster-Whisper (CTranslate2-optimized Whisper) |
| Voice Activity Detection | Silero VAD |
| Text-to-Speech | Piper TTS (streaming) |
| Agent Orchestration | LangGraph (stateful multi-node graph) |
| LLM | Groq API — LLaMA 3.1 70B |
| Vector Store | ChromaDB |
| Embeddings | SentenceTransformers (`all-MiniLM-L6-v2`) |
| Sentiment Analysis | Integrated in LangGraph agent node |

### Frontend
| Layer | Technology |
|---|---|
| Framework | React + Vite |
| Styling | Tailwind CSS |
| Audio | Web Audio API + MediaRecorder |
| Transport | Native WebSocket |

---

## 🏗️ Architecture

```
Browser (React/Vite)
        │
        │  WebSocket /ws/voice
        │  ├── Binary frames: raw PCM audio (int16, 16kHz, mono)
        │  └── Text frames:   JSON control messages
        │
        ▼
FastAPI WebSocket Handler (websocket.py)
        │
        ├── Audio Buffer → [64KB threshold]
        │
        ├── Faster-Whisper STT + Silero VAD
        │       └── transcript + language + is_speech
        │
        ├── LangGraph Agent (graph.py)
        │       ├── Node: RAG Retrieval (ChromaDB)
        │       ├── Node: Sentiment Analysis
        │       ├── Node: LLM Response (Groq LLaMA 3.1)
        │       ├── Node: Escalation Check
        │       └── Node: Session Summary (terminal)
        │
        └── Piper TTS → streamed audio chunks → browser
                └── asyncio.Task (cancellable for barge-in)
```

### How a turn works

1. Browser streams raw PCM audio over WebSocket binary frames
2. Server buffers audio until ~2 seconds accumulated (64KB threshold)
3. Faster-Whisper + Silero VAD transcribes and detects speech
4. Transcript is sent to LangGraph agent with full conversation history
5. Agent retrieves relevant FAQ chunks from ChromaDB, generates LLM response, scores sentiment
6. Response text and metadata sent to frontend
7. Piper TTS streams audio chunks back as base64 frames
8. Frontend plays audio; user can barge in at any point to cancel the TTS task

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.10+
- Node.js 18+
- [Groq API key](https://console.groq.com/)

### Backend

```bash
# Clone the repo
git clone https://github.com/yourusername/VoiceIQ.git
cd VoiceIQ/Backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set environment variables
copy .env.example .env
# Edit .env and add your GROQ_API_KEY

# Run the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd VoiceIQ/Frontend

npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

> **Note:** Browser microphone access requires either `localhost` or an HTTPS origin.

### Environment Variables

```env
GROQ_API_KEY=your_groq_api_key_here
```

---

## 📡 WebSocket Protocol

**Endpoint:** `ws://localhost:8000/ws/voice`

### Client → Server

| Frame Type | Content | Description |
|---|---|---|
| Binary | Raw PCM bytes (int16, 16kHz, mono) | Microphone audio stream |
| Text (JSON) | `{ "action": "end_session" }` | Flush buffer, generate summary, end session |
| Text (JSON) | `{ "action": "barge_in" }` | Cancel current TTS immediately |
| Text (JSON) | `{ "action": "clear_buffer" }` | Discard buffered audio |

### Server → Client

| Message Type | Payload | Description |
|---|---|---|
| `transcript` | `{ text, language, language_probability }` | STT result |
| `response` | `{ text, intent, confidence, should_escalate, summary, sentiment_score }` | Agent response |
| `tts_start` | — | TTS playback beginning |
| `audio` | `{ data: <base64 PCM> }` | TTS audio chunk |
| `tts_end` | — | TTS playback complete |
| `status` | `{ message }` | Connection / pipeline status |
| `error` | `{ message }` | Error notification |

---

## 🖼️ Demo

> Screenshots

| View | Description |
|---|---|
| 📸 Main UI | Live transcript panel, agent response, entity highlights |
| 📸 Escalation Alert | UI state when sentiment triggers human handoff |
| 📸 Session Summary | Structured summary generated at session end |

---

## 💡 Interview Highlights

These are the technically interesting decisions made during this project — the kind of things worth discussing in a placement interview:

**1. Why asyncio.create_task for TTS?**
The TTS synthesis loop is moved to a background asyncio task so the WebSocket receive loop stays unblocked. This is what makes barge-in actually work — the `{"action": "barge_in"}` message is received and `task.cancel()` is called immediately, rather than waiting for TTS to finish.

**2. LangGraph over a plain LLM call**
LangGraph gives each turn a stateful graph with discrete nodes: retrieval → sentiment → LLM → escalation check → (optional) summary. This makes it easy to add, remove, or reorder nodes without touching the rest of the pipeline, and the state dict flows cleanly through every node.

**3. Sentiment-based auto-escalation**
Rather than a keyword trigger, sentiment is scored on every turn and accumulated in `sentiment_history`. Two consecutive scores below -0.5 triggers escalation. This avoids false positives from a single frustrated sentence.

**4. RAG over a static FAQ**
Instead of stuffing the entire FAQ into the system prompt (which hits token limits and degrades response quality), FAQ chunks are embedded into ChromaDB at startup. Each turn retrieves the top-k relevant chunks and injects only those into the LLM context.

**5. Handling the `CancelledError` correctly**
When a TTS task is cancelled via `task.cancel()`, Python raises `asyncio.CancelledError` inside the task. The code catches it, sends a `tts_end` frame to cleanly close the frontend's audio state, then re-raises — which is the correct asyncio convention to allow the event loop to properly clean up the task.

---

## 📁 Project Structure

```
VoiceIQ/
├── Backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app entry point
│   │   ├── config.py             # Settings via pydantic-settings
│   │   ├── websocket.py          # WebSocket endpoint & voice pipeline
│   │   ├── stt/
│   │   │   └── pipeline.py       # Faster-Whisper + Silero VAD
│   │   ├── tts/
│   │   │   └── pipeline.py       # Piper TTS streaming
│   │   ├── agent/
│   │   │   └── graph.py          # LangGraph agent graph
│   │   └── rag/
│   │       └── retriever.py      # ChromaDB + SentenceTransformers
│   ├── requirements.txt
│   └── .env.example
└── Frontend/
    ├── src/
    │   ├── App.jsx               # Root component
    │   ├── components/
    │   │   ├── VoiceAgent.jsx    # Main UI + WebSocket logic
    │   │   └── TranscriptPanel.jsx
    │   └── utils/
    │       └── entityHighlight.js  # Regex entity highlighting
    ├── package.json
    └── vite.config.js
```

---

## 👤 Author

Built by [Your Name] as part of an AI portfolio for campus placements.

- GitHub: [@yourusername](https://github.com/yourusername)
- LinkedIn: [your-linkedin](https://linkedin.com/in/your-linkedin)

---

## 📄 License

MIT License — free to use and modify.