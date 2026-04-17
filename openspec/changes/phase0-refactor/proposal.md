# Phase 0 Refactor — Proposal

## Summary
Rebuild EchoLearn's subtitle pipeline and playback sync around a **Whisper-only time base**, migrate job and cache state to **SQLite**, split the oversized router/App modules, and introduce **React Router** to prepare for Phase 1 features. The change is scoped as a refactor + sync fix — no new user-facing features.

## Why this change exists
Users report that subtitle highlighting (both sentence- and word-level) visibly drifts from the audio. Root-cause analysis identified three compounding defects:

1. **Two time bases collide.** The current pipeline pulls captions from `youtube-transcript-api` (timing typically ±0.5–2s off the actual speech) and then stitches Whisper word timestamps onto them. Any point in the video can legitimately have two different "truths" for where a word ends.
2. **`estimate_word_timings` fabricates timings** when Whisper word data is missing by distributing word positions proportional to character counts. This is not real alignment; it is a plausible-looking guess.
3. **Frontend sync is lossy.** `useSubtitleSync` polls `getCurrentTime()` every 100ms and calls `setState` on every tick. That imposes a minimum ~100ms of visual lag and triggers 10 rerenders per second even when nothing changed.

Layered on top of the behavioral problem:
- `backend/app/routers/subtitles.py` is 455 lines and mixes HTTP, background orchestration, cache I/O, Whisper invocation, and translation — untestable in isolation.
- `frontend/src/App.tsx` is 305 lines and owns routing, job polling, player state, and view composition simultaneously.
- The in-memory job store is lost on backend restart; flat JSON cache files have no schema or relational structure.

## What changes — high level

- **Pipeline.** Drop `youtube-transcript-api`. Whisper word timestamps are the sole source of timing. A new `services/alignment/segmenter.py` derives sentence boundaries from the word stream using punctuation cues, silence gaps, and a hard duration cap.
- **Storage.** SQLite (`data/echolearn.db`, WAL mode) replaces the in-memory job dict and JSON cache. Tables: `jobs`, `videos`, `segments`. Repositories wrap access.
- **Backend structure.** `routers/` splits into `jobs.py`, `subtitles.py`, `videos.py`. `services/` gets `pipeline.py`, `transcription/`, `translation/`, `alignment/`. Background work goes through `jobs/runner.py` using `ThreadPoolExecutor(max_workers=2)`.
- **Frontend structure.** `react-router-dom` introduced; `/` HomePage and `/watch/:videoId` PlayerPage. Components move under `features/player/` and `features/jobs/`. Hooks split into `useYouTubePlayer`, `useSubtitleSync`, `useAutoPause`, `useKeyboardShortcuts`.
- **Sync core.** `useSubtitleSync` moves from 100ms polling to `requestAnimationFrame`, uses binary search for current segment/word, and setState only when indices change.
- **New endpoint.** `GET /api/videos` powers a HomePage history list.
- **Testing.** Pytest foundation (fake Whisper/translator clients, in-memory SQLite, TestClient integration tests). Vitest + MSW for frontend hook tests. ui-verifier agent runs Playwright against real dev servers to measure p95 sync delta.

## Out of scope — explicitly deferred

The following items are intentionally **not** part of Phase 0 and must not be added during this change:

- Streaming / incremental segment delivery (Phase 1)
- Personal video library with user accounts (Phase 1)
- Flashcard authoring or spaced repetition (Phase 2)
- Inline dictionary / word lookup (Phase 2)
- Pronunciation scoring, shadowing mode, export features (Phase 3)
- Multi-language targets beyond EN → ZH
- Mobile-native clients

## Risks

- **Whisper cost and latency.** Removing transcript fallback means every video pays the Whisper bill and the ~25–65% pipeline window. Mitigation: cache is authoritative; resubmitting a processed video returns instantly. 3-min video budget: ≤ 60s end-to-end.
- **Segmenter tuning.** Punctuation thresholds (≥3s min, 0.7s silence, 15s hard cap) are derived from design intuition, not measured data. Mitigation: unit tests lock current behavior; ui-verifier measures real p95; thresholds are constants, cheap to tune.
- **SQLite under concurrent jobs.** WAL mode + `ThreadPoolExecutor(max_workers=2)` bounds writer contention, but heavy concurrent submissions could still queue. Acceptable for Phase 0 scale (single dev / small pilot).
- **Refactor scope creep.** Migration touches nearly every module. Mitigation: the task order in `tasks.md` keeps the app runnable after each step — old router coexists with new infra until cutover.
- **Frontend Router + hook rewrite in same phase.** Two large reshuffles. Mitigation: router reshuffle (T06) must preserve behavior; hook rewrite (T07) gates on ui-verifier p95 evidence before marking done.

## Acceptance gates (Definition of Done)

- pytest, vitest, lint, and production build all green
- ui-verifier reports PASS with sentence p95 ≤ 100ms, word p95 ≤ 150ms
- `backend/app/routers/subtitles.py` < 150 lines; `frontend/src/App.tsx` < 150 lines
- Backend restart does not lose in-flight jobs (SQLite persistence verified)
- 3-minute video processed end-to-end in ≤ 60s
