# VoiceIQ 🎙️

> **Real-time voice AI customer service agent** — talks, listens, looks up and changes orders, hands over to a human, and measures itself.

---

## 📌 Project Overview

VoiceIQ is a full-stack voice agent for customer service. A caller speaks in the browser (or on a phone line); VoiceIQ transcribes the speech, runs a tool-calling agent, and answers in a synthesized voice — over one WebSocket, sentence by sentence, while the model is still writing.

What makes it more than a voice chatbot:

- **Streaming pipeline** — the first sentence is spoken while the LLM is still producing the rest, and every turn shows where its time went
- **An agent that acts** — it cancels orders, starts returns and changes delivery addresses in a real database, after a spoken confirmation
- **Caller verification** — nothing about an order is revealed or changed until the caller proves who they are
- **Human handoff console** — a supervisor watches calls live, reads an AI-written briefing, takes over and speaks to the caller
- **Multilingual** — English, Hindi and Tamil conversations over an English knowledge base
- **Post-call analytics** — every call is stored, summarised and scored; unanswered questions become a "knowledge gaps" list
- **Sentiment from the voice** — loudness and pitch are combined with the words, and plotted live
- **Evaluation harness** — replays recorded utterances and reports word error rate, intent accuracy and retrieval hit rate
- **Phone access** — the same pipeline answers a real phone number through Twilio
- **One-command start** — `docker compose up`

---

## ✨ Features

| Feature | How it works |
|---|---|
| 🎤 Turn-taking | Silero VAD ends a turn when the caller stops speaking — no fixed timer |
| ⚡ Barge-in | Speech during a reply cancels that turn on the server and stops playback |
| 🚀 Streaming replies | LLM tokens → sentence splitter → Piper TTS, each sentence sent as soon as it is ready |
| ⏱️ Latency breakdown | Per turn: waiting for silence, speech-to-text, understanding, first sentence, voice synthesis |
| 🛠️ Tool-calling agent | LangGraph agent with tools for FAQ search, order status, cancel, return, address change, escalation |
| ✅ Spoken confirmation | Changes are parked until the caller says yes; the "yes" is checked in code, not left to the model |
| 🔐 Caller verification | Last four digits of the phone number on the order; three failed attempts hand the call to a human |
| 🧑‍💼 Supervisor console | Live calls, escalation queue, handoff briefing, takeover with typed replies spoken to the caller |
| 🌐 Multilingual | Reply language per call; FAQ queries are translated to English by the agent before retrieval |
| 📊 Analytics | Resolution rate, escalation rate, estimated satisfaction, time to first audio, knowledge gaps |
| 😠 Voice sentiment | Pitch and loudness relative to the caller's own baseline, fused with text sentiment |
| 🧪 Evaluation | `python -m eval.run_eval` — WER, intent, tool and retrieval accuracy on recorded audio |
| ☎️ Phone bridge | Twilio Media Streams ⇄ the same call session (8 kHz mu-law ⇄ 16 kHz PCM) |
| 🛟 Failure isolation | An LLM or TTS error fails one turn with a message; the call stays connected |

---

## 🛠️ Tech Stack

### Backend
| Layer | Technology |
|---|---|
| API & WebSocket | FastAPI + Uvicorn |
| Speech-to-Text | Faster-Whisper (`base`) |
| Voice Activity Detection | Silero VAD |
| Text-to-Speech | Piper (`en_US-lessac-medium`, optional `hi_IN-pratham-medium`) |
| Agent | LangGraph + LangChain tool calling |
| LLM | Groq — `openai/gpt-oss-120b` (agent), `openai/gpt-oss-20b` (classification, summaries) |
| Vector Store | ChromaDB + SentenceTransformers (`all-MiniLM-L6-v2`) |
| Database | SQLite (orders, call history) |
| Phone | Twilio Media Streams |

### Frontend
| Layer | Technology |
|---|---|
| Framework | React 18 + Vite + React Router |
| Styling | Tailwind CSS |
| Mic capture | AudioWorklet, downsampled to 16 kHz PCM |
| Charts | Recharts |
| Transport | Native WebSocket |

---

## 🏗️ Architecture

```
Browser mic ──16 kHz PCM──►  /ws/voice  ─┐
Phone (Twilio) ─8 kHz µ-law─► /ws/twilio ─┤
                                          ▼
                              CallSession (app/call/session.py)
                              ├─ Silero VAD: start / end of speech, barge-in
                              └─ Turn task
                                  ├─ Faster-Whisper → transcript + prosody (pitch, loudness)
                                  ├─ LangGraph agent (app/agent/)
                                  │     triage ── sentiment + intent + yes/no  (fast model)
                                  │       ├─ frustrated twice / asks for a person → escalate
                                  │       ├─ an action awaits confirmation → resolve_pending ─┐
                                  │       ├─ unintelligible → fallback                        │
                                  │       └─ agent  ◄────────────────────────────────────────┘
                                  │            streams sentences, calls tools:
                                  │            search_faq · verify_customer · get_order_status
                                  │            cancel_order · start_return · update_shipping_address
                                  │            escalate_to_human
                                  │     summarize
                                  └─ Piper TTS worker: one sentence at a time → caller
                              ├─ SQLite: orders, calls, turns, knowledge gaps
                              └─ CallRegistry ──► /ws/supervisor (live board, takeover)
```

### How a turn works

1. Audio is buffered; Silero VAD checks the trailing 0.8 s for speech
2. When the caller stops, the utterance becomes a background task (so new speech can interrupt it)
3. Faster-Whisper transcribes it and prosody features are extracted from the same audio
4. **Triage** (one fast LLM call) scores sentiment, labels the intent and reads a yes/no answer
5. The **agent** streams its reply; each finished sentence goes straight to the TTS worker
6. Tools run in between — an order change is only *parked*, and executes after the caller confirms
7. The turn, its timings and any knowledge gap are stored; supervisors see the update live

### Safety rules built into the agent

- Order details and changes require **verification** — enforced inside the tools, not just in the prompt
- Every change needs a **spoken yes**; eligibility is re-checked when the change is applied
- The agent is told never to claim an action unless a tool result starts with `DONE`

---

## 🚀 Setup & Installation

### Option A — Docker

```bash
git clone https://github.com/mkarthikaravind1/VoiceIQ.git
cd VoiceIQ
copy .env.example .env        # then add your GROQ_API_KEY
docker compose up --build
```

Open `http://localhost:8080`. The first start downloads the speech models (about 300 MB) into a Docker volume.

### Option B — Local

Prerequisites: Python 3.10+, Node.js 18+, a [Groq API key](https://console.groq.com/).

```bash
cd VoiceIQ/Backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt

# .env lives in the repo root
copy ..\.env.example ..\.env
# Edit .env and add your GROQ_API_KEY

# Piper voice (~63 MB, not stored in git)
curl -L -o data/tts_models/en_US-lessac-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx

# Build the FAQ vector store (again whenever knowledge_base.json changes)
python -m app.rag.ingest

uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

```bash
cd VoiceIQ/Frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The sample order database is created on first start.

> Microphone access needs `localhost` or HTTPS. Use headphones when testing barge-in on loud speakers.

### Optional: Hindi voice

Replies in Hindi work as text without it; with it they are spoken.

```bash
curl -L -o data/tts_models/hi_IN-pratham-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx
curl -L -o data/tts_models/hi_IN-pratham-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx.json
```

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Required |
| `AGENT_MODEL` | `openai/gpt-oss-120b` | Model for the tool-calling agent |
| `LLM_MODEL` | `openai/gpt-oss-20b` | Model for triage, briefings and post-call analysis |
| `WHISPER_MODEL` / `WHISPER_DEVICE` / `WHISPER_COMPUTE_TYPE` | `base` / `cpu` / `int8` | Speech recognition |
| `WHISPER_LANGUAGE` | `en` | Language a call starts in; empty = auto-detect |
| `SUPPORTED_LANGUAGES` | `en,hi,ta` | Languages the caller may pick |
| `TTS_VOICES` | `hi:hi_IN-pratham-medium` | Extra Piper voices as `lang:model` pairs |
| `RAG_MAX_DISTANCE` / `RAG_WEAK_DISTANCE` | `0.8` / `0.6` | FAQ relevance cutoffs (cosine distance) |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Origins allowed to call the API and open WebSockets |
| `PUBLIC_HOST` | — | Public host for the Twilio phone bridge |
| `VITE_WS_URL` (frontend) | same host as the page | WebSocket URL of the backend |

Groq's free tier allows about 8,000 tokens per minute per model, which is a few turns per minute. Under heavier use a turn can pause for several seconds or fail with a retry message.

---

## 🧭 Trying it out

Sample orders (reset with `python -m app.db.store --reset`):

| Order | Customer | Phone ends | Status | Good for |
|---|---|---|---|---|
| 1001 | Rahul Sharma | 1234 | Delivered 4 days ago | starting a return |
| 1002 | Priya Patel | 5678 | In transit | status and tracking |
| 1003 | Arjun Mehta | 2468 | Processing | cancel, change address |
| 1004 | Sneha Joshi | 1357 | Cancelled | refund status |
| 1005 | Rahul Sharma | 1234 | Processing | cancel, change address |
| 1006 | Priya Patel | 5678 | Delivered 41 days ago | return refused (outside 30 days) |

A conversation to try:

1. "Where is my order one zero zero three?" → the agent asks for the last four phone digits
2. "Two four six eight" → verified; it reads the status
3. "Please cancel it" → it asks you to confirm
4. "Yes" → cancelled in the database
5. "I want to talk to a human" → open **Supervisor** in a second tab, read the briefing, take over and type a reply
6. Press **End call and summarise**, then open **Analytics**

---

## 🧪 Evaluation

```bash
cd Backend
python -m eval.make_audio            # speak the test sentences with Piper (once)
python -m eval.run_eval              # full run, uses the Groq API
python -m eval.run_eval --no-llm     # speech + retrieval only
```

`eval/cases.json` holds the test sentences with the expected intent, tool, FAQ and order number. The harness runs each one through the real STT, retrieval and agent code against a temporary copy of the database and reports:

| Metric | Meaning |
|---|---|
| Word error rate | speech-to-text errors against the reference sentence |
| Order numbers heard | spoken numbers recovered as digits |
| Retrieval hit rate | expected FAQ among the retrieved articles |
| Intent / tool accuracy | the agent filed the turn correctly and called the expected tool |

Synthetic speech is a best case. For a realistic score, record the sentences yourself and put them in `eval/audio/` under the same file names.

---

## ☎️ Phone calls (Twilio)

1. Expose the backend publicly, for example `ngrok http 8000`
2. Set `PUBLIC_HOST=<your-ngrok-host>` in `.env` and restart the backend
3. In the Twilio console, set your number's **Voice webhook** to `https://<your-ngrok-host>/twilio/voice` (HTTP POST)
4. Call the number

Phone calls appear on the Supervisor and Analytics pages like browser calls. Requests are not signature-checked yet — validate `X-Twilio-Signature` before production use.

---

## 📡 API

| Endpoint | Purpose |
|---|---|
| `WS /ws/voice` | Browser call. Binary frames: PCM int16 16 kHz mono. Text frames: JSON controls |
| `WS /ws/supervisor` | Live call board; actions `takeover`, `say`, `release` |
| `WS /ws/twilio`, `POST /twilio/voice` | Phone bridge |
| `GET /api/analytics/summary` · `/calls` · `/calls/{id}` | Analytics |
| `GET /api/calls/live` | Calls in progress |
| `GET /api/health` | Health check |

Messages on `/ws/voice` (server → client): `transcript`, `tool`, `partial`, `response`, `tts_start`, `audio`, `tts_end`, `metrics`, `barge_in`, `verified`, `language`, `handoff`, `call_summary`, `status`, `error`. Turn messages carry a `turn_id` so the client can drop anything from an interrupted turn. Controls (client → server): `end_session`, `barge_in`, `clear_buffer`, `set_language`, `end_call`. Full details are in the docstring of `Backend/app/api/websocket.py`.

The supervisor and analytics endpoints have no login. They are for local demos; add authentication before exposing them.

---

## 💡 Interview Highlights

**1. Streaming is a queue between two tasks.** The agent node emits each sentence as the LLM finishes it; a TTS worker consumes them. Cancelling the turn task (barge-in) cancels both.

**2. One call session, two transports.** The browser socket and the Twilio bridge only move audio. Turn-taking, the agent, persistence and handoff live in `CallSession`, so the phone channel was about 200 lines.

**3. Guardrails in code, not in the prompt.** Verification is checked inside every order tool. Changes are parked and executed by a separate graph node only after a classified "yes", and eligibility is re-checked at that moment.

**4. Two models, split by job.** A small fast model does classification and summaries; a stronger one does tool calling. It also splits the rate-limit budget.

**5. Turn IDs for stale messages.** After an interruption, audio for the old turn may already be on the wire. `barge_in` tells the client which turns to ignore.

**6. Sentiment relative to the caller.** Arousal is measured against that caller's running baseline, so a naturally loud voice is not read as anger. It is a transparent heuristic, not a trained emotion model.

**7. Knowledge gaps close the loop.** An FAQ search with no match, or only a weak one, is logged. The analytics page turns those into a list of articles worth writing.

**8. It measures itself.** The evaluation harness found a real bug during development: Whisper wrote "one thousand and three" as "1,000 and 3", which the order-number parser missed.

---

## 📁 Project Structure

```
VoiceIQ/
├── docker-compose.yml
├── .env.example
├── Backend/
│   ├── main.py                     # FastAPI app, model warm-up
│   ├── Dockerfile · docker_entrypoint.py
│   ├── app/
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── websocket.py        # /ws/voice (browser transport)
│   │   │   ├── supervisor.py       # /ws/supervisor
│   │   │   ├── analytics.py        # /api/analytics/*
│   │   │   ├── twilio.py           # phone bridge
│   │   │   └── health.py
│   │   ├── call/
│   │   │   ├── session.py          # CallSession: turn-taking, pipeline, handoff, analysis
│   │   │   └── registry.py         # live calls → supervisors
│   │   ├── agent/
│   │   │   ├── graph.py            # LangGraph wiring
│   │   │   ├── nodes.py            # triage, resolve_pending, agent, escalate, fallback
│   │   │   ├── tools.py            # FAQ, verification, order tools
│   │   │   ├── context.py          # per-call and per-turn state
│   │   │   ├── text.py             # spoken numbers, sentence splitter
│   │   │   ├── i18n.py · llm.py · state.py
│   │   ├── stt/                    # Faster-Whisper, Silero VAD, prosody
│   │   ├── tts/                    # Piper, per-language voices
│   │   ├── rag/                    # ChromaDB ingest + retriever
│   │   └── db/store.py             # SQLite: orders, calls, turns, knowledge gaps
│   ├── eval/                       # cases.json, make_audio.py, run_eval.py
│   └── data/                       # knowledge_base.json, orders_db.json (seed)
└── Frontend/
    ├── Dockerfile · nginx.conf
    └── src/
        ├── pages/                  # VoiceAgent, Supervisor, Analytics
        ├── components/             # CallLog, StatsBar, SentimentChart, LatencyBar, Header
        ├── hooks/                  # useVoiceSocket, useAudioPlayer
        ├── audio/pcm-worklet.js
        └── utils/                  # chartTheme, entities
```

---

## 👤 Author

Built by [Your Name] as part of an AI portfolio for campus placements.

- GitHub: [@mkarthikaravind1](https://github.com/mkarthikaravind1)
- LinkedIn: [your-linkedin](https://linkedin.com/in/your-linkedin)

---

## 📄 License

MIT License — free to use and modify.
