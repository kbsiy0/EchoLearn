# Phase 0 Refactor — Design

Readers should be able to implement from this document alone.

---

## Section 1 — Architecture

```
Frontend (React + Vite + React Router)
  src/
    routes/
      HomePage.tsx          (URL input + history list)
      PlayerPage.tsx        (player + subtitle panel)
    features/
      player/
        hooks/
          useYouTubePlayer.ts
          useSubtitleSync.ts
          useAutoPause.ts
          useKeyboardShortcuts.ts
        components/
          YouTubePlayer.tsx
          SubtitlePanel.tsx
          SentenceRow.tsx
      jobs/
        hooks/
          useJobPolling.ts
        components/
          JobProgress.tsx
    api/           (fetch wrappers for /api endpoints)
    lib/           (youtube URL parsing, time utilities)
    types/         (shared TS types)

Backend (FastAPI)
  app/
    routers/
      jobs.py              (POST/GET /api/subtitles/jobs)
      subtitles.py         (GET /api/subtitles/{video_id})
      videos.py            (GET /api/videos)
    services/
      pipeline.py          (orchestrator — probe → audio → whisper → segment → translate → persist)
      transcription/
        whisper.py         (OpenAI whisper-1 client wrapper)
        youtube_audio.py   (probe_metadata + download_audio; probe is metadata-only via yt-dlp --dump-json)
      translation/
        translator.py      (EN → ZH via gpt-4o-mini)
      alignment/
        segmenter.py       (word stream → sentence segments)
    repositories/
      jobs_repo.py         (CRUD for jobs table)
      videos_repo.py       (CRUD for videos + segments)
    db/
      schema.sql
      connection.py        (WAL-mode sqlite3 connection factory)
    jobs/
      runner.py            (ThreadPoolExecutor max_workers=2)
    models/
      schemas.py           (Pydantic request/response)

Storage
  data/echolearn.db        (SQLite, WAL)
  data/audio/*.mp3         (ephemeral, cleaned per-job + orphan sweep on startup)
```

### Runtime boundaries
- **Request thread** handles HTTP only; persistence via repositories; enqueues work by inserting a `jobs` row with status `queued` and submitting to the executor.
- **Worker thread** (from the pool) runs `pipeline.run(job_id)` which updates progress via `jobs_repo.update_progress`.
- **Database** is the only shared state; no module-level dicts, no background threads outside the pool.

### Identifier safety
`video_id` is always a YouTube canonical ID matching the regex `^[A-Za-z0-9_-]{11}$`. This regex is enforced at three layers:
1. HTTP intake — `POST /api/subtitles/jobs` rejects non-matching IDs with `INVALID_URL`.
2. Repository writes — every `jobs_repo` / `videos_repo` method that accepts `video_id` validates it before composing SQL or filesystem paths.
3. Audio pipeline — `youtube_audio.download_audio` validates before composing any `Path`, preventing traversal into `data/audio/..`.

---

## Section 2 — Data model

### SQLite schema

```sql
CREATE TABLE jobs (
  job_id TEXT PRIMARY KEY,
  video_id TEXT NOT NULL,
  status TEXT CHECK(status IN ('queued','processing','completed','failed')),
  progress INTEGER DEFAULT 0,
  error_code TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_jobs_video ON jobs(video_id);

CREATE TABLE videos (
  video_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  duration_sec REAL NOT NULL,
  source TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE segments (
  video_id TEXT REFERENCES videos(video_id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  start_sec REAL NOT NULL,
  end_sec REAL NOT NULL,
  text_en TEXT NOT NULL,
  text_zh TEXT NOT NULL,
  words_json TEXT NOT NULL,
  PRIMARY KEY (video_id, idx)
);
```

Rationale:
- `segments` are normalized (one row per sentence) so future per-segment joins (progress, flashcards) are cheap.
- `words_json` stays as a JSON blob because Phase 0 never queries by word — sentence is the smallest addressable unit in SQL.
- `ON DELETE CASCADE` lets us reprocess a video by deleting its `videos` row.

### Pydantic contracts

```python
class JobStatus(BaseModel):
    job_id: str
    video_id: str
    status: Literal['queued','processing','completed','failed']
    progress: int           # 0..100
    error_code: Optional[str]
    error_message: Optional[str]

class WordTiming(BaseModel):
    text: str
    start: float
    end: float

class Segment(BaseModel):
    idx: int
    start: float
    end: float
    text_en: str
    text_zh: str
    words: list[WordTiming]

class SubtitleResponse(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    segments: list[Segment]

class VideoSummary(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    created_at: str
```

### Progress ladder
A job's `progress` field advances monotonically through these ranges:

| Stage                                   | Range   |
|-----------------------------------------|---------|
| queued                                  | 0       |
| probe metadata + audio download         | 0–25    |
| whisper                                 | 25–65   |
| segmenter                               | 65–70   |
| translation (results held in memory)    | 70–95   |
| atomic persist (`publish_video(...)` — upsert + segments insert in one transaction) | 95–100  |

**Atomic publish.** Translation results are never written to the DB as they arrive. The pipeline accumulates the full `list[Segment]` in memory; then, at the 95→100 step, a single call to `publish_video(...)` performs an upsert on the `videos` row followed by insert of all `segments` rows, all within one SQLite transaction. If any prior stage fails, no `videos` or `segments` rows exist. This is Option A (see Section 4) and is referenced as an invariant in `specs/pipeline.md` and `specs/data-layer.md`. Readers who want internals see `specs/data-layer.md`.

### API endpoints

| Method | Path                              | Response          | Notes                                                        |
|--------|-----------------------------------|-------------------|--------------------------------------------------------------|
| POST   | `/api/subtitles/jobs`             | `JobStatus`       | Body: `{url}`. Returns existing job if video in-flight/cache |
| GET    | `/api/subtitles/jobs/{job_id}`    | `JobStatus`       | 404 if unknown                                               |
| GET    | `/api/subtitles/{video_id}`       | `SubtitleResponse`| 404 if not completed                                         |
| GET    | `/api/videos`                     | `list[VideoSummary]` | Ordered by `created_at DESC`                             |

Client contract for jobs/subtitles stays compatible with today's frontend during the refactor.

---

## Section 3 — Sync fix core

### Backend — `services/alignment/segmenter.py`

**Input.** Whisper's flat word list:
```python
Word = {"text": str, "start": float, "end": float}
```

**Output.** List of `Segment` values (without translation yet — `text_zh` is filled by the translator after segmentation).

**Algorithm.**
```
buffer = []
segments = []
for i, w in enumerate(words):
    buffer.append(w)
    duration = buffer[-1].end - buffer[0].start
    next_gap = words[i+1].start - w.end if i+1 < len(words) else None

    # Strip trailing closing quotes (straight + curly, single + double) before the punctuation check
    tail = w.text.rstrip().rstrip('"\u201D\u2019\'"')
    should_cut = (
        (tail.endswith(('.', '!', '?')) and duration >= 3.0)
        or (next_gap is not None and next_gap >= 0.7 and duration >= 3.0)
        or duration >= 15.0
    )
    if should_cut:
        segments.append(flush(buffer))
        buffer = []

if buffer:
    segments.append(flush(buffer))
```

`flush(buffer)` produces a segment where:
- `start` = `buffer[0].start`
- `end` = `buffer[-1].end`
- `text_en` = result of the whitespace-normalization rule below
- `words` = verbatim list from buffer (original `text` preserved for per-word display)

**Whitespace normalization rule (exact).**
1. For each word `w` in buffer: `token = w.text.strip()`.
2. Drop `token` if it is the empty string.
3. Join remaining tokens with a single ASCII space: `" ".join(tokens)`.
4. Collapse any run of ≥ 2 spaces to exactly one (`re.sub(r" {2,}", " ", s)`).

A fixture test case must include a real Whisper sample where tokens have leading spaces (e.g., `" world"`, `" ,"`) to lock this behavior.

**Why this works.** Every sentence's start and end come from the same time base as its words — no stitching, no drift. The 15s hard cap guarantees termination on talks with no punctuation. The 3s minimum prevents false cuts on filler like "Yeah." "OK." in quick succession.

**Edge cases handled in tests.**
- Empty word list → raise `ValueError("no speech detected")`, caller maps to `WHISPER_ERROR`.
- Single token → emits one segment.
- All-caps continuous speech (no punctuation) → cut solely by 15s cap.
- Last buffer at loop end is flushed even without a cut trigger.

### Frontend — `features/player/hooks/useSubtitleSync.ts`

```typescript
function useSubtitleSync(player: YT.Player | null, segments: Segment[]): {
  currentIndex: number;      // -1 if before first / after last
  currentWordIndex: number;  // -1 if between words
}
```

**Loop.** Replace `setInterval(…, 100)` with:
```typescript
const rafId = requestAnimationFrame(tick);
function tick() {
  if (!player) return;
  const t = player.getCurrentTime();
  const segIdx = binarySearchSegment(segments, t);
  const wordIdx = segIdx >= 0 ? binarySearchWord(segments[segIdx].words, t) : -1;
  if (segIdx !== lastSegIdx || wordIdx !== lastWordIdx) {
    setState({ currentIndex: segIdx, currentWordIndex: wordIdx });
    lastSegIdx = segIdx;
    lastWordIdx = wordIdx;
  }
  rafRef.current = requestAnimationFrame(tick);
}
```

**Binary search.** On an array sorted by `start`, find the largest `i` where `arr[i].start <= t` and `arr[i].end >= t`. Return -1 if no match.

**State stability.** `setState` is called only when at least one index changed. 60fps reads, but rerenders only on index transitions (typically a few per minute).

### Hook decomposition

```
features/player/hooks/
  useYouTubePlayer.ts       (IFrame API lifecycle: load, create, destroy)
  useSubtitleSync.ts        (time → {currentIndex, currentWordIndex})
  useAutoPause.ts           (pause at segment.end ± 0.08s epsilon, once per segment)
  useKeyboardShortcuts.ts   (space=play/pause, ←/→ jump ±1 segment, R=replay segment)
```

Auto-pause epsilon `0.08s` is carried over from the existing `useSubtitleSync`; revisit if p95 shifts post-RAF.

Each hook owns a single concern; `PlayerPage` composes them.

---

## Section 4 — Errors and edges

### Metadata probe precedes download
The pipeline's first step is `probe_metadata(url)` (metadata-only, via `yt-dlp --dump-json` or equivalent), which returns `VideoMetadata(video_id, title, duration_sec, source)`. Duration is checked against `MAX_VIDEO_MINUTES` **before** any audio is downloaded. `VIDEO_UNAVAILABLE` and `VIDEO_TOO_LONG` are raised from probe, never from `download_audio`. This ordering prevents paying the bandwidth cost of downloading a video that will be rejected.

### Error codes

| Code                | Retryable | Raised by          | When                                                 |
|---------------------|-----------|--------------------|------------------------------------------------------|
| `INVALID_URL`       | no        | HTTP intake (regex shape) OR `probe_metadata` (yt-dlp cannot parse URL as a YouTube video) | URL does not parse to a YouTube video ID, or `video_id` fails regex `^[A-Za-z0-9_-]{11}$`, or probe cannot parse the URL |
| `VIDEO_UNAVAILABLE` | no        | `probe_metadata`   | Private, deleted, region-locked, age-gated (detected via metadata probe) |
| `VIDEO_TOO_LONG`    | no        | `probe_metadata`   | `duration_sec / 60 > MAX_VIDEO_MINUTES` (detected before `download_audio` is ever invoked) |
| `FFMPEG_MISSING`    | no        | `download_audio`   | yt-dlp / audio extraction cannot run                 |
| `WHISPER_ERROR`     | yes       | Whisper / segmenter | Whisper call failed OR returned no words             |
| `TRANSLATION_ERROR` | yes       | Translator         | Translation API call failed                          |
| `INTERNAL_ERROR`    | yes       | Pipeline / runner  | Uncaught exception, or `processing` row swept at startup |

`NO_CAPTIONS` is removed — captions are no longer a concept in Phase 0.

**Precedence.** If `probe_metadata` cannot retrieve metadata at all (private, deleted, geo-blocked, or unparseable URL), raise `VIDEO_UNAVAILABLE` / `INVALID_URL` as appropriate. `VIDEO_TOO_LONG` is only reachable when probe successfully returns a `VideoMetadata` whose `duration_sec` exceeds `MAX_VIDEO_MINUTES * 60`. In particular, a private-and-too-long video always surfaces as `VIDEO_UNAVAILABLE` because probe never gets as far as reading duration.

### Edge cases

- **Empty Whisper output.** Segmenter raises; pipeline records `status='failed'`, `error_code='WHISPER_ERROR'`, `error_message='no speech detected'`.
- **Long unpunctuated run.** 15s hard cap keeps segments bounded; sentences may land mid-thought but timeline stays coherent.
- **Duplicate submission while in-flight.** `POST /api/subtitles/jobs` first looks up any non-terminal job for `video_id`; returns it instead of creating a new one.
- **Cache hit.** If a `videos` row exists, `POST` inserts a synthetic `completed` job and returns immediately.
- **Audio cleanup.** Pipeline deletes its own `data/audio/{video_id}.mp3` on success AND failure. On app startup, a sweep removes any `data/audio/*.mp3` with no corresponding `processing` job.
- **SQLite concurrency.** `PRAGMA journal_mode=WAL`, short transactions, `ThreadPoolExecutor(max_workers=2)`. A writer holds the lock only for the duration of a single UPDATE.
- **Orphaned `processing` job on restart.** Startup hook flips any `status='processing'` row older than the stale threshold to `status='failed'`, `error_code='INTERNAL_ERROR'`, `error_message='server restarted during processing'`. The threshold is a runner constructor argument (default 60s in production, overridable to e.g. `0.1s` in tests). Client can resubmit.

---

## Section 5 — Testing

### Backend

| Path                                       | Purpose                                                                 |
|--------------------------------------------|-------------------------------------------------------------------------|
| `tests/conftest.py`                        | In-memory SQLite fixture, fake Whisper client, fake translator client  |
| `tests/fixtures/`                          | Sample Whisper word lists for edge cases                                |
| `tests/unit/test_segmenter.py`             | Punctuation cuts, silence cuts, MAX_DUR cap, empty input, single token, all-caps-no-punct |
| `tests/unit/test_repositories.py`          | jobs_repo + videos_repo CRUD, concurrent progress updates               |
| `tests/integration/test_pipeline.py`       | Full pipeline with fake clients → DB final state correct                |
| `tests/integration/test_jobs_api.py`       | FastAPI TestClient: new-job, cache-hit, dup-submit, retry-after-fail    |

Fake clients are plain classes with the same method signatures as the real OpenAI clients; injected via dependency override in tests.

### Frontend

| Path                                              | Purpose                                               |
|---------------------------------------------------|-------------------------------------------------------|
| `src/features/player/hooks/useSubtitleSync.test.ts` | Binary search boundaries, no rerender when index unchanged |
| `src/features/player/hooks/useAutoPause.test.ts`  | Fires once at segment end; respects epsilon            |
| `src/features/jobs/hooks/useJobPolling.test.ts`   | Backoff, terminal-state stop, error propagation        |
| `src/lib/youtube.test.ts`                         | URL → video_id parsing across formats                  |

Stack: Vitest + React Testing Library + MSW for API mocking.

### UI / visual verification

Delegated to the **`ui-verifier` agent** at `.claude/agents/ui-verifier.md`. The agent:
- Boots real dev servers (backend on 8000, frontend on 5173)
- Drives Playwright through a representative flow
- Uses `browser_evaluate` to measure the delta between `player.getCurrentTime()` and the currently-highlighted segment/word at the same instant, across many samples
- Computes p95 for sentence-level and word-level deltas
- Writes a report to `docs/ui-verification/<task-id>.md` with PASS/FAIL and raw numbers

Every frontend-affecting task in `tasks.md` must include "dispatch ui-verifier" as a completion gate.

### Definition of Done (project-level)

- pytest + vitest + lint + production build all green
- ui-verifier reports PASS with sentence p95 ≤ 100ms, word p95 ≤ 150ms
- `backend/app/routers/subtitles.py` < 150 lines; `frontend/src/App.tsx` < 150 lines
- Backend restart does not lose job *records*: `processing` jobs stale for ≥ threshold transition to `failed` with `INTERNAL_ERROR: server restarted during processing` (SQLite persistence verified by integration test)
- 3-minute video processed end-to-end in ≤ 60s
- Global 200-line rule enforced across `backend/app/` and `frontend/src/` (no single `.py`/`.ts`/`.tsx` exceeds 200 lines)

---

## Section 6 — Migration order

Each step must leave the app runnable end-to-end. Ordering is reflected exactly in `tasks.md`.

1. **Testing foundation (T01).** pytest config, `conftest.py`, fake Whisper/translator clients, Vitest config, MSW setup. **No production code touched.** This is a hard prerequisite for every other task because every later task lands with tests.
2. **SQLite infrastructure (T02).** `db/schema.sql`, `db/connection.py`, `repositories/jobs_repo.py`, `repositories/videos_repo.py`. Old router untouched; new infra sits alongside.
3. **Pipeline rebuild (T03).** New `services/pipeline.py`, new `services/alignment/segmenter.py`, Whisper-only. `services/transcription/` and `services/translation/` extracted. `youtube-transcript-api` removed from `requirements.txt`.
4. **Jobs runner (T04).** `jobs/runner.py` with `ThreadPoolExecutor(max_workers=2)`. Replaces ad-hoc `threading.Thread`.
5. **Router split (T05).** `routers/jobs.py` + `routers/subtitles.py` + `routers/videos.py` wired through new repos. `app/cache/store.py` deleted. This is the cutover point — old router goes away.
6. **Frontend Router + directory reshuffle (T06).** Install `react-router-dom`. Create `routes/HomePage.tsx` and `routes/PlayerPage.tsx`. Move existing components into `features/player/` and `features/jobs/`. Behavior must be unchanged at this step.
7. **Frontend hooks rewrite (T07).** RAF loop, binary search, split into `useSubtitleSync` / `useAutoPause` / `useKeyboardShortcuts`. **ui-verifier runs here and must confirm p95 ≤ 100ms sentence / 150ms word before this task can be marked done.**
8. **Data cleanup (T08).** Delete `data/cache/*.json` and any remaining legacy modules. Verify startup sweep works.
9. **Final ui-verifier pass + integrator gate (T09).** End-to-end run on a representative 3-minute video, full DoD checklist.

Why this order:
- Tests first → every subsequent task is TDD.
- Data layer before pipeline → pipeline can persist as it's built.
- Pipeline before runner → runner wraps a working `pipeline.run`.
- Runner before router split → new routers enqueue via the runner from day one.
- Backend cutover before frontend router → API surface is stable before the frontend reshuffles.
- Frontend reshuffle before hook rewrite → new files exist to receive the rewritten hooks.
- Hook rewrite gated by ui-verifier → the sync fix is only real when measured.
