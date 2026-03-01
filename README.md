# EchoLearn

**Learn languages from YouTube, one sentence at a time.**

EchoLearn turns YouTube videos into interactive bilingual study material. Paste a video URL, get synchronized English + Traditional Chinese subtitles, and learn with sentence-by-sentence playback and real-time word highlighting.

Built for focused listening practice — pause at sentence boundaries, replay difficult lines, and follow each word as it is spoken.

![EchoLearn demo placeholder](https://placehold.co/1200x675?text=EchoLearn+Demo+Screenshot)

<!-- Replace above with actual screenshot or demo GIF -->

## Features

- **Bilingual subtitles** — English transcript paired with Traditional Chinese translation
- **Sentence-by-sentence playback** — auto-pause at sentence boundaries with prev / next / repeat navigation
- **Word-level highlighting** — active word is highlighted in real time as the video plays
- **Smart segment merging** — short caption fragments are merged into natural sentence-length chunks
- **Whisper fallback** — when YouTube captions are unavailable, audio is transcribed via OpenAI Whisper
- **Instant replay** — processed subtitles are cached per video for fast repeat access
- **Keyboard shortcuts** — `Space` play/pause, `←` prev, `→` next, `R` repeat

## Prerequisites

- Python 3.9+
- Node.js 18+
- [ffmpeg](https://ffmpeg.org/) (required for Whisper fallback)
- An [OpenAI API key](https://platform.openai.com/api-keys)

## Getting Started

```bash
git clone https://github.com/your-username/EchoLearn.git
cd EchoLearn
```

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example .env    # then edit .env and set OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** and paste a YouTube URL to start learning.

## Project Structure

```
EchoLearn/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI entry point
│   │   ├── config.py          # Environment variables & settings
│   │   ├── routers/           # API route handlers
│   │   ├── services/          # Business logic (pipeline, translation)
│   │   └── models/            # Pydantic schemas
│   ├── tests/                 # Pytest test suite
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.tsx            # Main app component
│   │   ├── components/        # UI components
│   │   ├── hooks/             # React hooks (player sync, subtitle sync)
│   │   ├── api/               # API client
│   │   ├── lib/               # Utilities
│   │   └── types/             # TypeScript type definitions
│   └── package.json
└── .env.example
```

## How It Works

```
YouTube URL
    │
    ▼
┌────────────────────┐
│  Validate URL &    │
│  create async job  │
└────────┬───────────┘
         │
    ┌────▼────┐    yes    ┌──────────────────┐
    │ Captions ├─────────►│ Extract captions  │
    │ exist?   │          └────────┬──────────┘
    └────┬────┘                   │
         │ no                     │
    ┌────▼──────────┐             │
    │ Download audio│             │
    │ + Whisper ASR │             │
    └────┬──────────┘             │
         │                        │
         └───────┬────────────────┘
                 ▼
    ┌────────────────────────┐
    │ Merge into sentences   │
    │ Translate EN → ZH-TW   │
    │ Attach word timings    │
    └────────────┬───────────┘
                 ▼
          Cache as JSON
```

## Configuration

Environment variables are read from `backend/.env`:

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key (translation + Whisper) |
| `CACHE_DIR` | No | `data/cache` | Cached subtitle JSON directory |
| `MAX_VIDEO_MINUTES` | No | `30` | Max input video length in minutes |

<details>
<summary>Supported YouTube URL formats</summary>

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://m.youtube.com/watch?v=VIDEO_ID`

</details>

## API

Base path: `/api/subtitles`

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/jobs` | Create a subtitle processing job from a YouTube URL |
| `GET` | `/jobs/{job_id}` | Poll job status (`queued` → `processing` → `completed` / `failed`) |
| `GET` | `/{video_id}` | Fetch cached bilingual subtitles for a processed video |

## Development

### Run tests

```bash
cd backend && python -m pytest tests/ -v
```

### Lint & build frontend

```bash
cd frontend
npm run lint
npm run build
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React, Vite, TypeScript, Tailwind CSS v4 |
| Backend | FastAPI, Python 3.9+ |
| AI | OpenAI GPT-4o-mini (translation), Whisper (transcription) |
| Storage | Local JSON file cache (no database) |

## Contributing

1. Fork the repo and create a feature branch.
2. Keep changes focused and include tests when behavior changes.
3. Run backend tests and frontend lint/build before opening a PR.
4. Open a pull request with a clear summary.

## License

MIT
