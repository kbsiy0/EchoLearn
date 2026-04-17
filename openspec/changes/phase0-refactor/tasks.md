# Phase 0 Refactor — Tasks

Ordering follows the migration plan in `design.md` Section 6.

**T01 is a cross-cutting prerequisite.** Every subsequent task depends on it because every subsequent task lands with tests.

Legend:
- **Dependencies** = tasks that must be complete before this one can start.
- **Parallelizable with** = tasks that may run concurrently (independent file sets, no handoff).
- **Required agents** = agents that must sign off before the task is considered done. `tdd-implementer` is always required. `ui-verifier` is required for any task that changes observable frontend behavior. `spec-reviewer` reviews every task at completion.

**Pre-flight check (applies to every task T01–T09):**
> tdd-implementer MUST verify `git branch --show-current` returns `change/phase0-refactor` before any file change. If on `main`, STOP and surface to parent; do not switch or commit.

---

## T01 — Testing foundation

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** none
- **Parallelizable with:** none (blocks all)
- **Blocks cross-cutting review for:** T02–T09 (every task lands with tests authored against this foundation)

**Acceptance criteria**
- `backend/tests/conftest.py` provides an in-memory SQLite fixture that creates all tables from `schema.sql` and yields a clean connection per test; sets `EL_TEST_STRICT=1` so progress regressions raise.
- `backend/tests/fakes/whisper.py` exposes `FakeWhisperClient` with the same method surface as the real client and returns a caller-supplied word list.
- `backend/tests/fakes/translator.py` exposes `FakeTranslator` that returns a deterministic EN→ZH mapping supplied per test.
- `backend/tests/fixtures/` contains at minimum: `whisper_normal.json`, `whisper_empty.json`, `whisper_allcaps_nopunct.json`, `whisper_leading_space_tokens.json`, `whisper_quote_trailing_punct.json`.
- `backend/tests/unit/test_sanity.py::test_truthy` exists (placeholder, asserts truthy) so `pytest` exits 0, not 5.
- `pytest backend/tests` exits 0 with at least 1 test passing.
- `frontend/vitest.config.ts` configured; `frontend/src/test/setup.ts` initializes MSW with an empty handler set.
- **Real frontend tests land in T01** (they author the tests that T06 will later move unchanged; implementation under test does not yet exist, so they use placeholder mock implementations that T06/T07 will replace):
  - `useJobPolling.test.ts` — fixed-interval polling, terminal-state stop, cancel-on-unmount
  - `useYouTubePlayer.test.ts` — IFrame API lifecycle (load/create/destroy) via mock
  - `useSubtitleSync.test.ts` — binary-search boundary cases
- `npm run test -- --run` exits 0 with tests passing.
- Tasks T02–T09 can `import` fakes/fixtures without modification.

**Files expected to touch**
- `backend/tests/conftest.py`
- `backend/tests/fakes/whisper.py`
- `backend/tests/fakes/translator.py`
- `backend/tests/fixtures/*.json`
- `backend/tests/unit/test_sanity.py`
- `backend/pyproject.toml` or `backend/pytest.ini`
- `frontend/vitest.config.ts`
- `frontend/src/test/setup.ts`
- `frontend/src/features/player/hooks/useYouTubePlayer.test.ts`
- `frontend/src/features/player/hooks/useSubtitleSync.test.ts`
- `frontend/src/features/jobs/hooks/useJobPolling.test.ts`
- `frontend/package.json` (add vitest, @testing-library/react, msw as devDeps)

**Required agents**
- tdd-implementer (builds the fixtures + real tests)
- spec-reviewer (gate: validates fakes match real client signatures; real tests present)

---

## T02 — SQLite infrastructure

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01
- **Parallelizable with:** none (T03 depends on repos)
- **Blocks cross-cutting review for:** T03, T04, T05

**Acceptance criteria**
- `backend/app/db/schema.sql` contains the three-table schema from design.md Section 2 verbatim.
- `backend/app/db/connection.py` exposes `get_connection()` returning a `sqlite3.Connection` with `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` applied.
- `backend/app/repositories/jobs_repo.py` implements: `create(job_id, video_id)`, `update_progress(job_id, progress)`, `update_status(job_id, status, error_code=None, error_message=None)`, `get(job_id)`, `find_active_for_video(video_id)`, `sweep_stuck_processing(older_than_sec: float)`.
- `backend/app/repositories/videos_repo.py` implements: `publish_video(video_id, title, duration_sec, source, segments)` (atomic single-transaction), `get_video(video_id)`, `list_videos()`, `get_segments(video_id)`.
- All write methods validate `video_id` against `^[A-Za-z0-9_-]{11}$` and raise on mismatch.
- `tests/unit/test_repositories.py` covers:
  - Every public method happy path.
  - **Progress monotonicity (a):** two threads call `update_progress(same_job_id, interleaved_values)` → final stored progress equals `max(values_attempted)` (highest wins). Under `EL_TEST_STRICT=1`, attempts to lower progress raise `AssertionError`.
  - **WAL concurrency (b):** two threads call `update_progress(different_job_ids)` → both complete within 200ms.
  - **Atomic publish:** simulated translation failure between probe and persist leaves no `videos` row and no `segments` rows.
  - **`video_id` regex enforcement at repo layer:** malformed IDs (`"short"`, `"has/slash..."`, empty) raise before any SQL executes.
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

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01, T02
- **Parallelizable with:** none

**Acceptance criteria**
- `backend/app/services/alignment/segmenter.py` implements the algorithm in design.md Section 3 and passes `tests/unit/test_segmenter.py` for: punctuation cut, silence cut, 15s hard cap, empty input raises `ValueError`, single token, all-caps-no-punctuation, leading-space tokens (whitespace normalization rule), quote-trailing punctuation (`."`, `.”`, `?'`).
- `backend/app/services/transcription/youtube_audio.py` exposes:
  - `probe_metadata(url) -> VideoMetadata` — metadata-only; raises `INVALID_URL`, `VIDEO_UNAVAILABLE`, `VIDEO_TOO_LONG`. Does NOT download audio.
  - `download_audio(video_id) -> Path` — raises `FFMPEG_MISSING`; validates `video_id` regex before any `Path` composition.
- `backend/app/services/transcription/whisper.py` wraps the Whisper client behind a class whose method signature matches `FakeWhisperClient`.
- `backend/app/services/translation/translator.py` wraps the translation client behind a class whose method signature matches `FakeTranslator`.
- `backend/app/services/pipeline.py` exposes `run(job_id)` orchestrating probe → download → whisper → segment → translate → atomic publish (via `videos_repo.publish_video`), updating progress per the ladder in design.md Section 2. Translation results are held in memory until the 95→100 persist step.
- `backend/requirements.txt` no longer lists `youtube-transcript-api`.
- `tests/integration/test_pipeline.py` runs the full pipeline with fakes and asserts: `videos` row written, `segments` rows written in order, `jobs` final status `completed`, `progress=100`, audio file deleted.
- `tests/integration/test_pipeline.py::test_audio_deleted_on_whisper_failure` — Whisper fake raises; audio file is still deleted, no `videos` or `segments` rows exist.
- `tests/integration/test_pipeline.py::test_video_too_long_detected_before_download` — probe returns duration > MAX; `download_audio` is never called (assert via fake).
- `tests/integration/test_pipeline.py::test_malformed_video_id_rejected` — repo layer rejects bad `video_id` even if somehow reached.
- All of `pytest backend/tests` green.

**Files expected to touch**
- `backend/app/services/alignment/segmenter.py`
- `backend/app/services/transcription/whisper.py`
- `backend/app/services/transcription/youtube_audio.py`
- `backend/app/services/translation/translator.py`
- `backend/app/services/pipeline.py`
- `backend/app/models/schemas.py` (VideoMetadata, Segment, WordTiming, SubtitleResponse, JobStatus, VideoSummary, CreateJobRequest)
- `backend/tests/unit/test_segmenter.py`
- `backend/tests/integration/test_pipeline.py`
- `backend/requirements.txt`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T04 — Jobs runner (ThreadPoolExecutor)

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01, T02, T03
- **Parallelizable with:** none

**Acceptance criteria**
- `backend/app/jobs/runner.py` exposes `JobRunner` with constructor arguments `max_workers: int = 2` and `stale_threshold_sec: float = 60.0`. Tests construct it with a short threshold (e.g., `0.1s`).
- `runner.submit(job_id)` calls `pipeline.run(job_id)` inside the executor and swallows exceptions after setting `jobs.status='failed'` with the appropriate `error_code`.
- `runner.startup_sweep()` uses the injected `stale_threshold_sec` to mark `processing` rows as `failed` with `INTERNAL_ERROR / server restarted during processing`.
- Runner lifecycle wired into FastAPI lifespan (startup calls `startup_sweep()`; shutdown calls `shutdown()`).
- `backend/tests/integration/test_startup_sweep.py` (named per reviewer) asserts:
  - With `stale_threshold_sec=0.1`, a `processing` row older than 100ms is swept to `failed` with `INTERNAL_ERROR`.
  - A fresh `processing` row (younger than threshold) is left untouched.
  - Production default of `60.0s` is verified via property/invariant test (construct runner with default, inspect attribute value; no wall-clock wait).
- `tests/integration/test_pipeline.py` extended to cover: runner handles failure paths and records error codes.
- pytest green.

**Files expected to touch**
- `backend/app/jobs/runner.py`
- `backend/app/main.py` (lifespan hook)
- `backend/tests/integration/test_pipeline.py`
- `backend/tests/integration/test_startup_sweep.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T05 — Router split + cutover

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01, T02, T03, T04
- **Parallelizable with:** none

**Acceptance criteria**
- `backend/app/routers/jobs.py` handles `POST /api/subtitles/jobs` and `GET /api/subtitles/jobs/{job_id}` using `jobs_repo` and `runner.submit`. Dup-submit returns existing in-flight job; cache-hit returns synthetic `completed` job.
- `POST /api/subtitles/jobs` body validation: `url: constr(max_length=2048)`. Invalid URL or `video_id` regex failure returns HTTP 400 with body `{error_code: 'INVALID_URL', error_message: <safe string>}`. `error_message` contains no stack trace or parser internals.
- `backend/app/routers/subtitles.py` handles `GET /api/subtitles/{video_id}` using `videos_repo`. File length < 150 lines.
- `backend/app/routers/videos.py` handles `GET /api/videos` returning `list[VideoSummary]` ordered by `created_at DESC`.
- `backend/app/cache/store.py` and any obsolete in-memory job dict deleted from `main.py`.
- **CORS preservation:** CORS middleware in `main.py` retains `allow_origins=['http://localhost:5173']` unchanged. Integration test `test_cors_preserved` sends `OPTIONS /api/videos` with an `Origin: http://localhost:5173` and asserts the response has `Access-Control-Allow-Origin: http://localhost:5173`.
- `tests/integration/test_jobs_api.py` covers: new submission, dup-submit returns same job, cache-hit short-circuits, retry after failure creates a new job, 404 on unknown job, 404 on unreached subtitles, HTTP 400 on invalid URL with sanitized error message, CORS preserved.
- `GET /api/videos` returns an empty list on a fresh DB and populated list after a completed job.
- pytest green, lint green.

**Files expected to touch**
- `backend/app/routers/jobs.py`
- `backend/app/routers/subtitles.py`
- `backend/app/routers/videos.py`
- `backend/app/main.py` (router registration + CORS retained)
- `backend/tests/integration/test_jobs_api.py`
- Delete: `backend/app/cache/store.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T06 — Frontend Router + directory reshuffle

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01 (tests), T05 (backend stable)
- **Parallelizable with:** none within frontend

**Acceptance criteria**
- `react-router-dom@^6.x` added to `frontend/package.json` (pinned to major 6).
- `frontend/src/App.tsx` composes `<BrowserRouter>` with `/` → `HomePage`, `/watch/:videoId` → `PlayerPage`. File length < 150 lines.
- `frontend/src/routes/HomePage.tsx` hosts URL input + history list (powered by `GET /api/videos`).
- `frontend/src/routes/PlayerPage.tsx` hosts player + subtitle panel.
- Components relocated under `frontend/src/features/player/components/` and `frontend/src/features/jobs/components/` — behavior unchanged from user's perspective.
- Existing hooks move (not rewritten) under `frontend/src/features/player/hooks/` and `frontend/src/features/jobs/hooks/`.
- **`useJobPolling` is CREATED in this task** (extracted from `App.tsx`'s inline polling), matching the contract in `specs/jobs-api.md` "Frontend consumer" section. Tests authored in T01 now pass against the real hook.
- Vitest suites (authored in T01) continue to pass with real implementations replacing any placeholder mocks; lint clean; `npm run build` succeeds.
- **ui-verifier dispatched — golden-path PASS required.** Smoke flow (URL → processed video → playback → navigate to HomePage history list) must return PASS. Timing p95 measurement is informational at this task only — the p95 gate is asserted in T07. Report: `docs/ui-verification/T06.md`.

**Files expected to touch**
- `frontend/src/App.tsx`
- `frontend/src/routes/HomePage.tsx`
- `frontend/src/routes/PlayerPage.tsx`
- `frontend/src/features/player/components/*.tsx` (moved)
- `frontend/src/features/jobs/components/*.tsx` (moved)
- `frontend/src/features/player/hooks/*.ts` (moved)
- `frontend/src/features/jobs/hooks/useJobPolling.ts` (CREATED)
- `frontend/src/api/*.ts`
- `frontend/src/lib/youtube.ts`
- `frontend/src/types/*.ts`
- `frontend/package.json`

**Required agents**
- tdd-implementer
- ui-verifier (gate: golden-path PASS)
- spec-reviewer

---

## T07 — Frontend hooks rewrite (sync fix)

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01, T06
- **Parallelizable with:** none

**Acceptance criteria**
- `useYouTubePlayer` isolated to IFrame API lifecycle only (no subtitle logic).
- `useSubtitleSync` uses `requestAnimationFrame` loop, binary search for segment and word, and calls `setState` only when at least one index changes. Returns `{ currentIndex, currentWordIndex }`.
- `useAutoPause` fires exactly once at `segment.end ± 0.08s` per segment.
- `useKeyboardShortcuts` binds space (play/pause), ←/→ (jump ±1 segment), R (replay current segment from its start).
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

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T05, T07
- **Parallelizable with:** none (T09 is strictly sequential after T08)

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
- `backend/tests/integration/test_startup_sweep.py` (extended for audio sweep)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T09 — Final ui-verifier pass + integrator gate

- **Pre-flight:** verify branch `change/phase0-refactor`. If on main, STOP and surface.
- **Dependencies:** T01–T08 (strictly sequential after T08)
- **Parallelizable with:** none

**Acceptance criteria**
- End-to-end run against a representative 3-minute English YouTube video completes in ≤ 60 seconds from `POST /api/subtitles/jobs` to `completed`.
- ui-verifier produces `docs/ui-verification/T09-final.md` with PASS + sentence p95 ≤ 100ms + word p95 ≤ 150ms on the same video.
- Backend is killed mid-job and restarted; the orphan sweep marks the job `failed` with `INTERNAL_ERROR / server restarted during processing`, and resubmitting the same URL creates a fresh job that completes normally.
- `backend/app/routers/subtitles.py` line count < 150 (verified in report).
- `frontend/src/App.tsx` line count < 150 (verified in report).
- **Global 200-line rule.** Running `find backend/app frontend/src \( -name '*.py' -o -name '*.tsx' -o -name '*.ts' \) -type f -print0 | xargs -0 wc -l | awk '$1 > 200 && $2 != "total"'` returns no rows. Report records the command + empty output.
- `pytest`, `vitest`, `eslint`, `npm run build`, `ruff`/`mypy` (if configured) all green.
- Integrator sign-off records all of the above in `docs/ui-verification/T09-final.md`.

**Files expected to touch**
- `docs/ui-verification/T09-final.md`
- (No production code changes — verification task only; if any remediation is needed, loop back to the relevant task.)

**Required agents**
- ui-verifier (final pass)
- spec-reviewer (final sign-off)
