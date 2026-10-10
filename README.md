# GD Arena

Practice campus-placement group discussions (GDs) by voice, against a live panel of AI participants.

> **Problem statement:** PS-__ *(fill in your problem statement number)*
> **Live app:** https://__.vercel.app *(fill in)* · **Backend:** https://__.onrender.com/health *(fill in)*

---

## What it does

GD Arena puts you in a spoken group discussion with 3 to 5 AI panelists, each with a distinct personality: a moderator, a dominator, a data-driven analyst, a bridger, and a quiet analyst. They debate your chosen topic out loud, turn to you with questions, react to what you actually say, and when time is up the moderator sums up the discussion and you get a scored report with quotes from your own answers.

## Done / Left / Plan

### Done (works now)

- **Lobby:** pick a topic (placement classics, abstract, or your own), the panel size (3 to 5), the language (English (India), English (US), Hindi, or Hinglish), and the length (presets from 1 minute, or any 1 to 60 minutes). Optionally add your tech field and the topics you know, and the panel tailors its questions to you.
- **Live voice discussion:**
  - Panelists speak with distinct voices and take turns with natural gaps. The next line is prepared while the current one plays, so there is no dead air.
  - Every few turns a panelist asks you a direct question. The mic opens only then, so speaker echo can't derail the discussion.
  - If you're silent for 1.5 s, the asker checks in ("Can you hear me? Should I repeat the question?"). Ask for a repeat and they rephrase it; say "I'd like to continue another day" and the moderator summarizes and ends the session.
- **Adaptive, on-topic panel:** the opening, the replies to your answers, the check-ins, the repeats, the time-up line and the summary are all generated from the topic and the conversation so far. Every prompt keeps the panel strictly on topic.
- **Time limit:** when the timer runs out, the moderator cuts in (even mid-sentence), says time is up, summarizes, and the report opens.
- **Detailed report:**
  - An overall score, plus a score out of 10 for each of fluency, accent & clarity, logic & structure, knowledge & relevance, confidence & responsiveness, and listening & engagement. Each comes with a reason and a specific tip.
  - What went well, and a ranked list of what to improve.
  - Measured delivery stats: speaking pace, filler words, questions answered, response time.
  - Speaking time against an equal share, the speaker-balance chart, quote-backed feedback cards, and the full transcript. It survives a page refresh.
- **Voices:** female personas (Anushka, Priya) speak with female voices, both with Sarvam and with the browser's fallback voice.
- **Installable mobile app (PWA):** phone-first layout, an install prompt on Android and desktop Chrome, and "Add to Home Screen" steps on iPhone.
- **Tests:** 48 backend tests (turn-taking, check-ins, repeats, time-up, personalization, topic rules, languages, scoring, services), plus browser end-to-end runs against a mock backend.

### Left (next 16 hours)

1. Run full sessions on the deployed stack with a live Sarvam key, and tune latency (speech-to-text, then LLM, then text-to-speech) on real networks.
2. The "Interruptions handled" metric is always 0 now that the panel hands you the floor. Replace it with "questions answered" and "average response time".
3. Session history: today, only the last report is kept, in the browser.
4. Light theme (the design system supports it; only dark is wired up).
5. Frontend unit tests for the audio hook (the queue, speech detection and floor gating).

### Plan to finish

- **Hours 0–4:** deploy, then run 10 live sessions across topics and both languages. Log timings and fix the slowest step first (we expect TTS), for example by streaming or by shorter first sentences.
- **Hours 4–8:** replace the interruptions metric in the evaluator and the report. Add a "your answers" section with per-answer feedback.
- **Hours 8–12:** add session history in the browser's local storage (lightweight, no accounts), with a progress view across sessions.
- **Hours 12–16:** frontend tests for the audio hook, accessibility and phone polish, demo rehearsal.

## Architecture and why

```
 Browser (Next.js PWA)                          Backend (FastAPI on Render)
 ┌──────────────────────────────┐   WebSocket   ┌──────────────────────────────────┐
 │ Lobby → Arena → Report       │ ◄───────────► │ /ws/gd  GDOrchestrator           │
 │ useGDSocket hook:            │  JSON events  │  turn engine (floor handoff,     │
 │  mic → AudioWorklet → 16 kHz │  (SCHEMA.md)  │  check-ins, time-up, summary)    │
 │  PCM16 + speech detection    │               │  ├─ Sarvam Saaras  speech→text   │
 │  clip queue → Web Audio      │               │  ├─ Sarvam LLM     panel lines   │
 │  (browser voice if no audio) │               │  ├─ Sarvam Bulbul  text→speech   │
 └──────────────────────────────┘               │  └─ evaluator      final report  │
                                                └──────────────────────────────────┘
```

- **One WebSocket, typed JSON events:** the contract lives in [`SCHEMA.md`](SCHEMA.md) and is mirrored by [`frontend/types/gd.ts`](frontend/types/gd.ts). A single socket carries mic audio up and voice clips, transcript lines, the timer and the floor changes down.
  - *Why:* a GD is a continuous two-way conversation. A socket keeps the latency low and lets the server lead the turn-taking, so it can hand you the floor, cut in when time is up, or check in when you're silent.
- **The server owns turn-taking; the browser reports playback:**
  - The backend decides who speaks next. It generates the following line while the current clip plays, then waits for the browser's `playback_finished` before opening the floor, so the 1.5 s silence timer starts exactly when the question ends.
  - The browser sends audio only while you hold the floor and are actually speaking. This uses its own speech detection, with 300 ms of lead-in so your first word isn't cut off.
  - *Why:* the bots stay audible (speaker echo can't cut them off), the rhythm stays natural, and no bandwidth is spent streaming silence.
- **AI service: Sarvam AI for speech-to-text, the LLM, and text-to-speech:**
  - *Why:* it is built for Indian languages and accents. It supports Hinglish and Indic languages natively, and has Indian voices for the panel.
  - One provider keeps the latency predictable and the setup to a single API key.
- **Audio format:** 16-bit PCM, 16 kHz mono, in 100 ms chunks.
  - *Why:* speech-to-text takes it directly with no decoding step, and the chunks are small enough to keep latency low.
- **Data store: none on the server, by design:**
  - A session lives in memory for as long as its WebSocket is open. The last report is kept in the browser's `sessionStorage`, so it survives a refresh.
  - *Why:* practice audio and transcripts are personal. Not storing them avoids privacy risk and consent flows, and keeps the backend stateless and cheap to host.
- **Mock mode:** without an API key, the backend uses deterministic, topic-aware lines and the browser speaks them with its built-in voice.
  - *Why:* development, tests and demos work offline at no cost.

## What we added (beyond the brief)

- **Floor handoff instead of free-for-all barge-in:** panelists invite you with direct questions.
  - *Why:* it stops speaker echo from cutting off the bots (the bug behind "the bots can't be heard"), and it mirrors real moderated GDs.
- **Silence check-in after 1.5 s, and repeat-in-simpler-words:** this is what a real panelist does. It also shows when the problem is the mic rather than the candidate.
- **"Continue another day" with a spoken summary:** ending early still gives closure and a report.
- **Time limit with a moderator cut-in and summary:** anything from a 1-minute drill to a full 60-minute session.
- **Personalized questions:** from your tech field and the topics you know, so practice matches your actual interviews.
- **Hinglish mode:** many Indian campus GDs are bilingual.
- **Installable PWA:** practice from your home screen, full screen, like a native app.
- **Transcript synced to the voice:** each line appears when that panelist starts speaking.

## How to run it

**Prerequisites:** Node 20+ and Python 3.11+. A [Sarvam AI](https://www.sarvam.ai/) API key is optional: without one, the app runs in mock mode and the browser's voice reads the panel's lines.

```bash
# Backend (run from the repo root: the code imports the `backend` package)
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# backend/.venv/bin/python -m pip install -r requirements.txt     # macOS/Linux
cp backend/.env.example backend/.env    # add SARVAM_API_KEY for real voices
backend/.venv/Scripts/python -m uvicorn backend.main:app --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev          # http://localhost:3000
```

- **Test login:** none needed. There are no accounts.
- **Tests:** `backend/.venv/Scripts/python -m pytest backend/tests`
- **Deployment:**
  - **Backend on Render:** uses [`render.yaml`](render.yaml), which builds and starts from the repo root. Set `SARVAM_API_KEY` in the Render dashboard.
  - **Frontend on Vercel:** set `NEXT_PUBLIC_WS_URL=wss://<your-render-service>.onrender.com/ws/gd`.
- **Tip:** wear headphones, and allow the microphone when the browser asks.

## Tools and AI used

- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, lucide-react. Audio uses the Web Audio API (an AudioWorklet for capture, AudioContext playback) and the Web Speech API as a fallback voice.
- **Backend:** FastAPI, Uvicorn, httpx, pydantic-settings, pytest.
- **AI models (Sarvam AI):**
  - Saaras (`saaras:v4`): speech-to-text.
  - Sarvam chat completions (`sarvam-2b` by default, falling back to `sarvam-105b`): panel dialogue and the evaluation.
  - Bulbul (`bulbul:v3`): text-to-speech.
- **How users are told they are talking to AI:**
  - The lobby says "the **AI panelists** discuss it live", and the panel slider is labelled "AI panelists".
  - In the arena, every panelist's seat is labelled with its role and "AI", for example "Moderator · AI".
  - The report calls the other side "AI panel".
  - Panelist names are personas, and only the candidate's seat says "You".
- **AI-assisted development:** parts of this codebase were written with Claude Code (Anthropic), and the commits say so.

## Who it is for

- **Who:** final-year students and freshers preparing for campus-placement GD rounds, especially those without a practice group, those nervous about speaking up, and those whose GDs happen in Hinglish.
- **Why they come back:**
  - Every session is different: the topic, the panel mix and the generated questions vary.
  - Sessions are short: a 1-minute or 5-minute drill fits between classes.
  - The report gives concrete, quote-backed feedback and a number to beat next time, such as speaking time against an equal share and the initiative score.
  - The personalized questions keep it relevant to the roles they're interviewing for.
