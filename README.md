# EchoLearn

Learn languages from YouTube, one sentence at a time.

EchoLearn is an AI-powered language learning app that turns YouTube videos into interactive bilingual study material. Paste a video URL and EchoLearn generates synchronized English + Traditional Chinese subtitles, then guides you through the video with sentence-by-sentence playback and real-time word highlighting.

It is built for focused listening practice: pause at sentence boundaries, replay difficult lines, and follow each word as it is spoken.

## 🎬 Demo

> Add your screenshots or GIF here.

![EchoLearn demo placeholder](https://placehold.co/1200x675?text=EchoLearn+Demo+Screenshot)

- Web app URL: `http://localhost:5173` (local dev)
- API URL: `http://localhost:8000`

## ✨ Highlights

- Bilingual subtitles: English transcript with Traditional Chinese translation
- Sentence-by-sentence learning: auto-pause and quick prev/next/repeat navigation
- Word-level sync: active word highlighting during playback
- Smart segment merging: converts short caption fragments into natural sentence chunks
- Whisper fallback: transcribes audio when YouTube captions are unavailable
- Fast repeat usage: subtitle results are cached per video ID
- Keyboard shortcuts: `Space` play/pause, `←` previous, `→` next, `R` repeat

## 🚀 Quick Start

### 1. Clone the repo

```bash
git clone https://github.com/your-username/EchoLearn.git
cd EchoLearn
```

### 2. Start the backend (FastAPI)

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env
# edit backend/.env and set OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

### 3. Start the frontend (React + Vite)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` and paste a YouTube URL to begin.

## Configuration

EchoLearn uses environment variables in `backend/.env`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | `""` | OpenAI API key for translation and Whisper transcription |
| `CACHE_DIR` | No | `data/cache` | Directory for cached subtitle JSON files |
| `MAX_VIDEO_MINUTES` | No | `30` | Maximum allowed input video duration |

### System prerequisites

- Python `3.9+`
- Node.js `18+`
- `ffmpeg` (required for Whisper fallback)

### Supported YouTube URL formats

- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
- `https://www.youtube.com/shorts/VIDEO_ID`
- `https://www.youtube.com/embed/VIDEO_ID`
- `https://m.youtube.com/watch?v=VIDEO_ID`

## How It Works

EchoLearn uses a small, practical pipeline:

1. Validate URL and create a background subtitle job.
2. Try YouTube captions first.
3. If captions are missing, download audio and transcribe with Whisper.
4. Merge caption fragments into sentence-level segments.
5. Translate segments EN → Traditional Chinese.
6. Attach word timings (Whisper timings when available, estimated otherwise).
7. Cache result JSON for instant future reuse.

### Architecture (concise)

- Frontend: React + Vite UI, YouTube IFrame player integration, subtitle sync hooks.
- Backend: FastAPI job endpoints, processing pipeline, cache read/write.
- AI services: OpenAI models for translation and fallback transcription.
- Storage: local JSON cache (no database required).

## API Reference

Base path: `/api/subtitles`

### `POST /jobs`
Create a subtitle job from a YouTube URL.

- Returns job metadata (`job_id`, `status`, `progress`, `video_id`).
- If cached subtitles already exist, returns a completed status immediately.

### `GET /jobs/{job_id}`
Check job status.

- Status lifecycle: `queued` → `processing` → `completed` or `failed`.
- Includes progress percentage and structured error info on failure.

### `GET /{video_id}`
Fetch cached subtitle payload for a processed video.

- Returns title, bilingual sentence segments, word timings, and source (`youtube_captions` or `whisper`).

### Common error codes

- `INVALID_URL`
- `VIDEO_PRIVATE`
- `NO_CAPTIONS`
- `OPENAI_ERROR`
- `VIDEO_TOO_LONG`

## 🛠 Development & Testing

### Backend

```bash
cd backend
python -m pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm run lint
npm run build
```

## 🤝 Contributing

Contributions are welcome.

1. Fork the repo and create a feature branch.
2. Keep changes scoped and include tests when behavior changes.
3. Run backend tests and frontend lint/build before opening a PR.
4. Open a pull request with a clear summary and screenshots for UI changes.

## License

MIT
