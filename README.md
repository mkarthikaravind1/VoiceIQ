# VoiceIQ 🎙️

> **Real-time voice AI customer service agent** — browser-based, with barge-in interruption, sentiment-based escalation, multi-turn memory, and RAG-powered FAQ retrieval.

---

## 📌 Project Overview

VoiceIQ is a full-stack real-time voice agent built for customer service automation. The user speaks into their browser; VoiceIQ transcribes the speech, runs it through an AI agent, and responds with synthesized voice — all over a single WebSocket connection, with no page reloads.

Key differentiators over a basic chatbot:
- **Natural turn-taking**: the agent waits until you stop speaking (voice activity detection), not for a fixed timer
- **Barge-in**: start talking while the agent is speaking and it stops immediately
- **Sentiment escalation**: detects frustrated users and auto-escalates to human support
- **RAG/FAQ retrieval**: grounds responses in a knowledge base using vector search
- **Multi-turn memory**: keeps recent conversation context for the whole call
- **Order lookup**: understands spoken order numbers ("one zero zero two", "ten oh two")

---

## ✨ Features

| Feature | Description |
|---|---|
| 🎤 Real-time STT | Faster-Whisper transcribes each utterance once Silero VAD detects the speaker has stopped |
| 🔊 Streaming TTS | Piper synthesizes the reply sentence by sentence, so audio starts before the full reply is ready |
| ⚡ Barge-in | Speech detected during a reply cancels that turn on the server and stops playback in the browser |
| 😠 Sentiment Escalation | Two consecutive turns below -0.5 sentiment trigger a human handoff alert |
| 🔍 RAG / FAQ Retrieval | ChromaDB + SentenceTransformers retrieve relevant FAQs; unrelated questions get no context |
| 🧠 Multi-turn Memory | The last 6 turns are passed to the LLM on every turn |
| 📦 Order Lookup | Order status from a JSON order store, with spoken-number normalisation |
| 🏷️ Entity Highlighting | Order numbers, emails and phone numbers are highlighted in the transcript |
| 📋 Per-turn Summary | Each turn is tagged with intent, resolution, order ID and processing time |
| 🛟 Failure isolation | An LLM or TTS error fails one turn with a message; the call stays connected |

Speech recognition is set to English by default, because the voice, prompts and knowledge base are English. Set `WHISPER_LANGUAGE=` (empty) in `.env` to let Whisper auto-detect the language.

---

## 🛠️ Tech Stack

### Backend
| Layer | Technology |
|---|---|
| API & WebSocket | FastAPI + Uvicorn |
| Speech-to-Text | Faster-Whisper (CTranslate2-optimized Whisper, `base` model) |
| Voice Activity Detection | Silero VAD (endpointing + barge-in detection) |
| Text-to-Speech | Piper TTS (`en_US-lessac-medium`) |
| Agent Orchestration | LangGraph (stateful multi-node graph) |
| LLM | Groq API — `llama-3.1-8b-instant` |
| Vector Store | ChromaDB (cosine similarity) |
| Embeddings | SentenceTransformers (`all-MiniLM-L6-v2`) |

### Frontend
| Layer | Technology |
|---|---|
| Framework | React 18 + Vite |
| Styling | Tailwind CSS |
| Mic capture | Web Audio API — AudioWorklet, downsampled to 16 kHz PCM |
| Playback | Web Audio API (queued WAV chunks) |
| Charts | Recharts |
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
FastAPI WebSocket Handler (app/api/websocket.py)
        │
        ├── Receive loop: buffer audio, Silero VAD on the trailing 0.8s
        │       ├── speech starts → cancel any running turn, send "barge_in"
        │       └── speech ends   → start a turn (background asyncio task)
        │
        └── Turn task
                ├── Faster-Whisper STT → transcript
                ├── LangGraph Agent (app/agent/graph.py)
                │       analyze_sentiment
                │         ├─ frustrated twice → escalate
                │         └─ detect_intent
                │               ├─ faq          → faq_retrieve (ChromaDB) → generate_response
                │               ├─ order_lookup → lookup_order            → generate_response
                │               ├─ escalate     → escalate
                │               └─ low confidence → fallback
                │       generate_summary (every path)
                └── Piper TTS → WAV chunk per sentence → browser
```

### How a turn works

1. The browser streams 16 kHz PCM audio over WebSocket binary frames
2. The server buffers audio and checks the trailing 0.8 seconds for speech with Silero VAD
3. When the speaker stops (or after 15 seconds), the utterance is handed to a background task
4. Faster-Whisper transcribes it; the transcript is sent to the browser
5. The LangGraph agent scores sentiment, detects intent, retrieves FAQ or order data, and generates a reply
6. The reply text and metadata are sent to the browser
7. Piper synthesizes the reply sentence by sentence; each sentence is sent as a base64 WAV chunk
8. If the user starts speaking at any point, the server cancels the turn and the browser stops playback

Every turn message carries a `turn_id`, so the browser can discard anything that belongs to an interrupted turn.

---

## 🚀 Setup & Installation

### Prerequisites
- Python 3.10+
- Node.js 18+
- [Groq API key](https://console.groq.com/)

### Backend

```bash
# Clone the repo
git clone https://github.com/mkarthikaravind1/VoiceIQ.git
cd VoiceIQ/Backend

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r requirements.txt

# Set environment variables (.env lives in the repo root)
copy ..\.env.example ..\.env
# Edit .env and add your GROQ_API_KEY

# Download the Piper voice model (~63 MB, not stored in git)
curl -L -o data/tts_models/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx

# Build the FAQ vector store (once, and again whenever knowledge_base.json changes)
python -m app.rag.ingest

# Run the server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd VoiceIQ/Frontend

npm install
npm run dev
```

Open `http://localhost:5173` in your browser. The dev server proxies `/ws`, `/api` and `/docs` to the backend on port 8000.

> **Note:** Browser microphone access requires either `localhost` or an HTTPS origin. Use headphones when testing barge-in on loud speakers, so the agent does not hear its own voice.

### Environment Variables

Backend (`.env` in the repo root or in `Backend/`):

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Required. Groq API key |
| `LLM_MODEL` | `llama-3.1-8b-instant` | Groq model name |
| `WHISPER_MODEL` | `base` | Faster-Whisper model size |
| `WHISPER_DEVICE` | `cpu` | `cpu` or `cuda` |
| `WHISPER_COMPUTE_TYPE` | `int8` | CTranslate2 compute type |
| `WHISPER_LANGUAGE` | `en` | Empty value = auto-detect |
| `RAG_MAX_DISTANCE` | `0.8` | FAQs further than this (cosine distance) are ignored |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins allowed to call the API and open the WebSocket |

Frontend (optional, `Frontend/.env`):

| Variable | Purpose |
|---|---|
| `VITE_WS_URL` | Full WebSocket URL of the backend, if it is not on the same host as the page |

---

## 📡 WebSocket Protocol

**Endpoint:** `ws://localhost:8000/ws/voice` (or `/ws/voice` through the Vite dev server)

### Client → Server

| Frame Type | Content | Description |
|---|---|---|
| Binary | Raw PCM bytes (int16, 16kHz, mono) | Microphone audio stream |
| Text (JSON) | `{ "action": "end_session" }` | Mic turned off — process any speech still buffered |
| Text (JSON) | `{ "action": "barge_in" }` | Cancel the current turn |
| Text (JSON) | `{ "action": "clear_buffer" }` | Discard buffered audio |

### Server → Client

| Message Type | Payload | Description |
|---|---|---|
| `transcript` | `{ text, language, language_probability, turn_id }` | STT result |
| `response` | `{ text, intent, confidence, should_escalate, summary, sentiment_score, turn_id }` | Agent response |
| `tts_start` | `{ turn_id }` | Synthesis beginning |
| `audio` | `{ data: <base64 WAV>, turn_id }` | One sentence of TTS audio |
| `tts_end` | `{ turn_id }` | Synthesis complete (playback may still be running) |
| `barge_in` | `{ turn_id }` | User started speaking — stop playback, ignore turns ≤ `turn_id` |
| `status` | `{ message }` | Connection / pipeline status |
| `error` | `{ message }` | A turn failed; the connection stays open |

---

## 💡 Interview Highlights

These are the technically interesting decisions made during this project:

**1. Why each turn runs as an `asyncio` task**
STT, the agent and TTS run in a background task, so the WebSocket receive loop never stops reading audio. That is what makes barge-in possible: the loop sees new speech while the agent is still thinking or talking, and calls `task.cancel()`.

**2. VAD endpointing instead of fixed-size chunks**
Cutting audio every N seconds splits sentences mid-word. Instead, Silero VAD checks the trailing 0.8 seconds of the buffer on every frame: the first speech marks the start of an utterance, and the first silent window marks the end.

**3. Turn IDs to discard stale messages**
After an interruption, audio for the old turn may already be on the wire. Every message carries a `turn_id`; `barge_in` tells the browser which turns to ignore, and the audio player uses a generation counter so a chunk that is still decoding never plays.

**4. LangGraph over a plain LLM call**
Each turn flows through discrete nodes: sentiment → intent → retrieval or order lookup → response → summary. Nodes can be added or reordered without touching the rest of the pipeline.

**5. Sentiment-based auto-escalation**
Sentiment is scored on every turn and kept in `sentiment_history`. Two consecutive scores below -0.5 trigger escalation, which avoids false positives from one frustrated sentence.

**6. RAG with a relevance cutoff**
Only the FAQs nearest to the question are sent to the LLM, and anything beyond a cosine-distance threshold is dropped — so an off-topic question gets "I don't have that information" rather than an answer built from unrelated FAQs.

**7. Failure isolation**
A Groq rate limit or a malformed LLM reply fails only that turn. The user hears nothing wrong with the connection and can simply ask again.

---

## 📁 Project Structure

```
VoiceIQ/
├── .env.example
├── Backend/
│   ├── main.py                     # FastAPI app, model warm-up (lifespan)
│   ├── requirements.txt
│   ├── app/
│   │   ├── config.py               # Settings via pydantic-settings
│   │   ├── api/
│   │   │   ├── health.py           # GET /api/health
│   │   │   └── websocket.py        # /ws/voice — turn-taking, barge-in
│   │   ├── stt/
│   │   │   ├── pipeline.py         # Faster-Whisper
│   │   │   └── vad.py              # Silero VAD
│   │   ├── tts/
│   │   │   └── pipeline.py         # Piper TTS, sentence streaming
│   │   ├── agent/
│   │   │   ├── state.py            # AgentState
│   │   │   ├── nodes.py            # sentiment, intent, lookup, response, summary
│   │   │   └── graph.py            # LangGraph wiring
│   │   └── rag/
│   │       ├── ingest.py           # Build the ChromaDB collection
│   │       └── retriever.py        # Query it
│   └── data/
│       ├── knowledge_base.json     # FAQs
│       ├── orders_db.json          # Sample orders
│       └── tts_models/             # Piper voice (downloaded, see Setup)
└── Frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── pages/
        │   └── VoiceAgent.jsx      # Main page
        ├── components/
        │   ├── CallLog.jsx         # Transcript log
        │   ├── IntentBadge.jsx
        │   └── StatsBar.jsx        # Intent pie + reply time
        ├── hooks/
        │   ├── useVoiceSocket.js   # WebSocket + mic capture
        │   └── useAudioPlayer.js   # Queued playback
        ├── audio/
        │   └── pcm-worklet.js      # AudioWorklet: resample to 16 kHz PCM
        └── utils/
            └── entities.js         # Entity highlighting
```

---

## 👤 Author

Built by [Your Name] as part of an AI portfolio for campus placements.

- GitHub: [@mkarthikaravind1](https://github.com/mkarthikaravind1)
- LinkedIn: [your-linkedin](https://linkedin.com/in/your-linkedin)

---

## 📄 License

MIT License — free to use and modify.
