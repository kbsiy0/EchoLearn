# Phase 0 Refactor — Tasks

Ordering follows the migration plan in `design.md` Section 6.

**T01 is a cross-cutting prerequisite.** Every subsequent task depends on it because every subsequent task lands with tests.

Legend:
- **Dependencies** = tasks that must be complete before this one can start.
- **Parallelizable with** = tasks that may run concurrently (independent file sets, no handoff).
- **Required agents** = agents that must sign off before the task is considered done. `tdd-implementer` is always required. `ui-verifier` is required for any task that changes observable frontend behavior. `spec-reviewer` reviews every task at completion.

---

## T01 — Testing foundation

- **Dependencies:** none
- **Parallelizable with:** none (blocks all)
- **Blocks cross-cutting review for:** T02–T09 (every task lands with tests authored against this foundation)

**Acceptance criteria**
- `backend/tests/conftest.py` provides an in-memory SQLite fixture that creates all tables from `schema.sql` and yields a clean connection per test.
- `backend/tests/fakes/whisper.py` exposes `FakeWhisperClient` with the same method surface as the real client and returns a caller-supplied word list.
- `backend/tests/fakes/translator.py` exposes `FakeTranslator` that returns a deterministic EN→ZH mapping supplied per test.
- `backend/tests/fixtures/` contains at least three sample Whisper word lists (normal, empty, all-caps-no-punct) as JSON.
- `pytest backend/tests` runs cleanly (zero tests pass, but collection succeeds) and `pytest --collect-only` lists the fakes/fixtures as importable.
- `frontend/vitest.config.ts` configured; `frontend/src/test/setup.ts` initializes MSW with an empty handler set; `npm run test -- --run` exits 0 with no tests.
- Tasks T02–T09 can `import` fakes/fixtures without modification.

**Files expected to touch**
- `backend/tests/conftest.py`
- `backend/tests/fakes/whisper.py`
- `backend/tests/fakes/translator.py`
- `backend/tests/fixtures/*.json`
- `backend/pyproject.toml` or `backend/pytest.ini` (pytest config)
- `frontend/vitest.config.ts`
- `frontend/src/test/setup.ts`
- `frontend/package.json` (add vitest, @testing-library/react, msw as devDeps)

**Required agents**
- tdd-implementer (builds the fixtures)
- spec-reviewer (gate: validates fakes match real client signatures and fixtures cover stated edge cases)

---

## T02 — SQLite infrastructure

- **Dependencies:** T01
- **Parallelizable with:** none (T03 depends on repos)
- **Blocks cross-cutting review for:** T03, T04, T05

**Acceptance criteria**
- `backend/app/db/schema.sql` contains the three-table schema from design.md Section 2 verbatim.
- `backend/app/db/connection.py` exposes `get_connection()` returning a `sqlite3.Connection` with `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` applied.
- `backend/app/repositories/jobs_repo.py` implements: `create(job_id, video_id)`, `update_progress(job_id, progress)`, `update_status(job_id, status, error_code=None, error_message=None)`, `get(job_id)`, `find_active_for_video(video_id)`, `sweep_stuck_processing(older_than_sec)`.
- `backend/app/repositories/videos_repo.py` implements: `upsert_video(video_id, title, duration_sec, source)`, `insert_segments(video_id, segments)`, `get_video(video_id)`, `list_videos()`, `get_segments(video_id)`.
- `tests/unit/test_repositories.py` covers every public method including concurrent progress updates from two threads.
- `pytest backend/tests/unit/test_repositories.py` green.
- Old pipeline continues to work unchanged.

**Files expected to touch**
- `backend/app/db/schema.sql`
- `backend/app/db/connection.py`
- `backend/app/repositories/jobs_repo.py`
- `backend/app/repositories/videos_repo.py`
- `backend/tests/unit/test_repositories.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T03 — Pipeline rebuild (Whisper-only)

- **Dependencies:** T01, T02
- **Parallelizable with:** none

**Acceptance criteria**
- `backend/app/services/alignment/segmenter.py` implements the algorithm in design.md Section 3 and passes `tests/unit/test_segmenter.py` for: punctuation cut, silence cut, 15s hard cap, empty input raises `ValueError`, single token, all-caps-no-punctuation.
- `backend/app/services/transcription/whisper.py` wraps the Whisper client behind a class whose method signature matches `FakeWhisperClient`.
- `backend/app/services/transcription/youtube_audio.py` downloads audio to `data/audio/{video_id}.mp3` and raises `FFMPEG_MISSING` / `VIDEO_UNAVAILABLE` / `VIDEO_TOO_LONG` as specified.
- `backend/app/services/translation/translator.py` wraps the translation client behind a class whose method signature matches `FakeTranslator`.
- `backend/app/services/pipeline.py` exposes `run(job_id)` that orchestrates download → whisper → segment → translate → persist, updating progress per the ladder in design.md Section 2.
- `backend/requirements.txt` no longer lists `youtube-transcript-api`.
- `tests/integration/test_pipeline.py` runs the full pipeline with fakes and asserts: `videos` row written, `segments` rows written in order, `jobs` final status `completed`, `progress=100`, audio file deleted.
- All of `pytest backend/tests` green.

**Files expected to touch**
- `backend/app/services/alignment/segmenter.py`
- `backend/app/services/transcription/whisper.py`
- `backend/app/services/transcription/youtube_audio.py`
- `backend/app/services/translation/translator.py`
- `backend/app/services/pipeline.py`
- `backend/app/models/schemas.py` (Segment, WordTiming, SubtitleResponse, JobStatus, VideoSummary)
- `backend/tests/unit/test_segmenter.py`
- `backend/tests/integration/test_pipeline.py`
- `backend/requirements.txt`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T04 — Jobs runner (ThreadPoolExecutor)

- **Dependencies:** T01, T02, T03
- **Parallelizable with:** none

**Acceptance criteria**
- `backend/app/jobs/runner.py` exposes `submit(job_id)` and `shutdown()`, wrapping a module-level `ThreadPoolExecutor(max_workers=2)`.
- `submit(job_id)` calls `pipeline.run(job_id)` inside the executor and swallows exceptions after setting `jobs.status='failed'` with the appropriate `error_code`.
- Runner startup sweeps any `status='processing'` rows older than 60 seconds to `failed` with `INTERNAL_ERROR` / `server restarted during processing`.
- Runner shutdown is wired into FastAPI lifespan events.
- `tests/integration/test_pipeline.py` extended to cover: runner handles failure paths and records error codes; startup sweep marks orphans.
- pytest green.

**Files expected to touch**
- `backend/app/jobs/runner.py`
- `backend/app/main.py` (lifespan hook)
- `backend/tests/integration/test_pipeline.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T05 — Router split + cutover

- **Dependencies:** T01, T02, T03, T04
- **Parallelizable with:** none

**Acceptance criteria**
- `backend/app/routers/jobs.py` handles `POST /api/subtitles/jobs` and `GET /api/subtitles/jobs/{job_id}` using `jobs_repo` and `runner.submit`. Dup-submit returns existing in-flight job; cache-hit returns synthetic `completed` job.
- `backend/app/routers/subtitles.py` handles `GET /api/subtitles/{video_id}` using `videos_repo`. File length < 150 lines.
- `backend/app/routers/videos.py` handles `GET /api/videos` returning `list[VideoSummary]` ordered by `created_at DESC`.
- `backend/app/cache/store.py` and any obsolete in-memory job dict deleted from `main.py`.
- `tests/integration/test_jobs_api.py` covers: new submission, dup-submit returns same job, cache-hit short-circuits, retry after failure creates a new job, 404 on unknown job, 404 on unreached subtitles.
- `GET /api/videos` returns an empty list on a fresh DB and populated list after a completed job.
- pytest green, lint green.

**Files expected to touch**
- `backend/app/routers/jobs.py`
- `backend/app/routers/subtitles.py`
- `backend/app/routers/videos.py`
- `backend/app/main.py` (router registration)
- `backend/tests/integration/test_jobs_api.py`
- Delete: `backend/app/cache/store.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T06 — Frontend Router + directory reshuffle

- **Dependencies:** T01 (tests), T05 (backend stable)
- **Parallelizable with:** none within frontend

**Acceptance criteria**
- `react-router-dom` added to `frontend/package.json`.
- `frontend/src/App.tsx` composes `<BrowserRouter>` with `/` → `HomePage`, `/watch/:videoId` → `PlayerPage`. File length < 150 lines.
- `frontend/src/routes/HomePage.tsx` hosts URL input + history list (powered by `GET /api/videos`).
- `frontend/src/routes/PlayerPage.tsx` hosts player + subtitle panel.
- Components relocated under `frontend/src/features/player/components/` and `frontend/src/features/jobs/components/` — behavior unchanged from user's perspective.
- Existing hooks move (not rewritten) under `frontend/src/features/player/hooks/` and `frontend/src/features/jobs/hooks/`.
- Vitest suites continue to pass; lint clean; `npm run build` succeeds.
- ui-verifier runs a smoke flow (URL → processed video → playback) and reports PASS on behavior unchanged (sync p95 measurement is informational only at this step).

**Files expected to touch**
- `frontend/src/App.tsx`
- `frontend/src/routes/HomePage.tsx`
- `frontend/src/routes/PlayerPage.tsx`
- `frontend/src/features/player/components/*.tsx` (moved)
- `frontend/src/features/jobs/components/*.tsx` (moved)
- `frontend/src/features/player/hooks/*.ts` (moved)
- `frontend/src/features/jobs/hooks/*.ts` (moved)
- `frontend/src/api/*.ts`
- `frontend/src/lib/youtube.ts`
- `frontend/src/types/*.ts`
- `frontend/package.json`

**Required agents**
- tdd-implementer
- ui-verifier (smoke — behavior parity)
- spec-reviewer

---

## T07 — Frontend hooks rewrite (sync fix)

- **Dependencies:** T01, T06
- **Parallelizable with:** none

**Acceptance criteria**
- `useYouTubePlayer` isolated to IFrame API lifecycle only (no subtitle logic).
- `useSubtitleSync` uses `requestAnimationFrame` loop, binary search for segment and word, and calls `setState` only when at least one index changes. Returns `{ currentIndex, currentWordIndex }`.
- `useAutoPause` fires exactly once at `segment.end ± 0.08s` per segment.
- `useKeyboardShortcuts` binds space (play/pause), ←/→ (jump ±1 segment), R (replay current segment).
- Vitest: `useSubtitleSync.test.ts` asserts binary search boundaries and that `setState` is not called when indices don't change across many raf ticks.
- **ui-verifier dispatched on real dev servers, produces report at `docs/ui-verification/T07.md` with sentence p95 ≤ 100ms AND word p95 ≤ 150ms.** Task cannot be marked done without this report.
- `App.tsx` line count verified < 150.

**Files expected to touch**
- `frontend/src/features/player/hooks/useYouTubePlayer.ts`
- `frontend/src/features/player/hooks/useSubtitleSync.ts`
- `frontend/src/features/player/hooks/useAutoPause.ts`
- `frontend/src/features/player/hooks/useKeyboardShortcuts.ts`
- `frontend/src/features/player/hooks/useSubtitleSync.test.ts`
- `frontend/src/features/player/hooks/useAutoPause.test.ts`
- `frontend/src/routes/PlayerPage.tsx` (compose rewritten hooks)

**Required agents**
- tdd-implementer
- ui-verifier (gate: p95 thresholds)
- spec-reviewer

---

## T08 — Data cleanup

- **Dependencies:** T05, T07
- **Parallelizable with:** T09 preparation (but T09 gates on this)

**Acceptance criteria**
- `backend/data/cache/*.json` deleted from repo and `.gitignore`.
- `backend/app/cache/` directory removed entirely (any leftover modules).
- Startup orphan sweep of `data/audio/*.mp3` verified by integration test: files with no matching `processing` job are removed within 1 second of app start.
- Fresh clone + first run produces `data/echolearn.db` and no stale JSON.
- pytest green.

**Files expected to touch**
- Delete: `backend/data/cache/` (directory)
- Delete: `backend/app/cache/` (directory)
- `backend/app/main.py` (startup sweep wiring, if not already in T04)
- `backend/.gitignore`
- `backend/tests/integration/test_startup_sweep.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T09 — Final ui-verifier pass + integrator gate

- **Dependencies:** T01–T08
- **Parallelizable with:** none

**Acceptance criteria**
- End-to-end run against a representative 3-minute English YouTube video completes in ≤ 60 seconds from `POST /api/subtitles/jobs` to `completed`.
- ui-verifier produces `docs/ui-verification/T09-final.md` with PASS + sentence p95 ≤ 100ms + word p95 ≤ 150ms on the same video.
- Backend is killed mid-job and restarted; the orphan sweep marks the job `failed`, and resubmitting the same URL creates a fresh job that completes normally.
- `backend/app/routers/subtitles.py` line count < 150 (verified in report).
- `frontend/src/App.tsx` line count < 150 (verified in report).
- `pytest`, `vitest`, `eslint`, `npm run build`, `ruff`/`mypy` (if configured) all green.
- Integrator sign-off records all of the above in `docs/ui-verification/T09-final.md`.

**Files expected to touch**
- `docs/ui-verification/T09-final.md`
- (No production code changes — verification task only; if any remediation is needed, loop back to the relevant task.)

**Required agents**
- ui-verifier (final pass)
- spec-reviewer (final sign-off)
