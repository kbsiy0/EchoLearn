# Phase 1b: Segment Streaming — Proposal

## Summary
Transform the Phase 0 "block-and-wait" subtitle pipeline into a **per-chunk streaming** pipeline. The backend cuts the audio into 2–4 chunks (first 60s, then 300s each) and runs Whisper sequentially, appending segments to the DB after every chunk. The frontend submits the URL, navigates immediately to `/watch/:videoId`, and polls `GET /subtitles/{videoId}` — which during processing returns 200 with partial segments + job status + progress %. The YouTube IFrame player is **not mounted** until processing completes. Loop, speed, and sync invariants from Phase 1a are untouched.

- **Change id:** `phase1b-segment-streaming`
- **Branch:** `change/phase1b-segment-streaming`

## Why this change exists
Phase 0 made a deliberate trade-off: the whole pipeline runs to completion before the frontend sees any subtitle data. That is acceptable at 3-minute videos (SLO < 60s) but breaks down at 20 minutes:

1. **Perceived progress.** A single `progress` percentage on an otherwise-blank page for 2+ minutes reads as "stuck." Users cannot tell whether the job is alive, slow, or dead.
2. **Time-to-first-subtitle (TTFS).** A learner should be able to *see* the first sentence of the video within seconds, even if they cannot play yet. Block-and-wait makes this impossible — the first sentence arrives at the same moment as the last.
3. **Whisper single-file limit.** OpenAI Whisper caps single uploads at 25 MB (~25 min of audio at our bitrate). Going beyond 10 minutes without chunking is fragile; 20 minutes is outright impossible without splitting the audio.

Phase 1b addresses all three with one mechanism — chunked, sequential Whisper calls with append-only DB writes.

## What changes — high level

- **Audio chunking.** A new `audio_chunking.py` service computes a schedule: first chunk 60s (drives TTFS), subsequent chunks 300s, with a 3s overlap on each internal boundary for Whisper's edge-artifact tolerance. Extraction uses `ffmpeg -y -ss X -to Y -i S -c copy -avoid_negative_ts make_zero OUT` per chunk (the `-to` form + `make_zero` flag are required to keep Whisper timestamps alignable with video-absolute time; see `design.md` §2).
- **Sequential per-chunk pipeline.** `Pipeline.run` is restructured: probe → upsert video row → download → **for each chunk:** extract → Whisper → clip overlap → sentence-carryover → translate → `append_segments` → `update_progress`. Chunks run strictly in order; a chunk's segments are visible to readers as soon as its DB write commits.
- **Sentence carryover.** A new `sentence_carryover.py` holds the final partial sentence of a chunk (no `.!?` terminator) and prepends it to the next chunk's word stream before segmentation. Keeps sentence boundaries semantically intact across chunks.
- **Per-chunk retry.** Each chunk retries Whisper up to 2 times on transient failure (network, rate-limit, timeout). Three failures on one chunk → job marked `failed`; already-appended segments from earlier chunks are **retained** for partial-result UX.
- **API shape evolution.** `GET /api/subtitles/{video_id}` response gains four fields: `status`, `progress`, `error_code`, `error_message`. Returns `200` for any state where a job exists for that `video_id` (including `queued`, `processing`, `failed`). Returns `404` only if no job for this `video_id` was ever submitted. Completed-state shape remains byte-compatible with Phase 0.
- **Frontend flow flip.** `HomePage` no longer uses `useJobPolling` and no longer shows a loading spinner after submit — it `navigate`s to `/watch/:videoId` as soon as `createJob` returns. `PlayerPage` is promoted from "read completed subtitles" to "read the live video view": it polls `/subtitles/{videoId}` at 1s, branches on `status`, and renders either a `ProcessingPlaceholder` (processing / failed-with-0-segments) or the Phase 1a player (completed / failed-with-partial-segments still mounts the placeholder; player stays unmounted).
- **New PlayerPage states.** `processing` → placeholder block with progress % and "正在處理字幕..." + `SubtitlePanel` appending partial segments as they arrive; player un-mounted. `failed + partial segments` → placeholder block with error message and "回首頁" button, plus the partial `SubtitlePanel` read-only. `failed + no segments` → error page with "回首頁". `completed` → full Phase 1a player (no behavior change).

## Out of scope — explicitly deferred

- **Parallel chunk processing.** Chunks run sequentially. Parallel would halve wall-clock but introduces concurrency, out-of-order DB writes, and multi-chunk failure bookkeeping — all expensive to test. Phase 1b stays sequential; re-visit if 3-minute SLO becomes the bottleneck.
- **Partial-range playback.** The player remains "un-mounted until completed." Allowing play within the already-transcribed range means a player ready-range abstraction, seek guards, and new sync edge cases — all previously rejected in brainstorming (Q3=A).
- **Streaming transport (SSE / WebSocket).** The frontend polls every 1s. Real streaming is a transport change with no UX gain here — 1s latency on "字幕 append" is imperceptible next to Whisper's 3–15s per-chunk cost.
- **Videos > 20 minutes.** `MAX_VIDEO_MINUTES` is lowered from `30` (unverified) to `20` (tested SLO). 60-minute videos, quota enforcement, and long-job cancellation are Phase 2+.
- **Cancellation of in-flight jobs.** The `failed` path exists but there is no user-initiated cancel (Phase 2).
- **Word-level streaming.** Words still arrive batched per segment; a sentence is not published to the DB until its last word has been transcribed (this is a property of the segmenter, unchanged).
- **`current_stage` field on `JobStatus`.** Considered and rejected — the `progress` % plus append-visible segments already convey liveness; a string enum would only couple frontend strings to backend implementation details.
- **Any Phase 1a behavior change.** Loop, speed, auto-pause, `?measure=1` semantics, localStorage, sync precision bar all carry through untouched.
- **Schema change for `segments` table.** The append write path uses the existing `(video_id, idx)` PK; no DDL needed.

## Risks

- **TTFS budget tight at 15s.** Components: probe (~3s) + download (~8s) + chunk-0 extract (~0.5s) + chunk-0 Whisper (~3–6s) + chunk-0 segment (<50ms) + chunk-0 translate (~2s) ≈ 16.5–19.5s in the common case. **This is over SLO.** Mitigation: (1) translate runs only on segments *ending* in `.!?` — open sentences held by carryover are not translated yet, cutting translate latency on chunk 0 to near-zero in the common case; (2) acceptance gate accepts `p50 ≤ 15s` rather than hard p95, with ui-verifier reporting both; (3) if p50 still breaks, reduce first-chunk to 45s in a follow-up (backend-only change).
- **Chunk-boundary word loss or duplication.** Whisper's output near edges is unreliable. The 3s overlap + per-chunk clipping to "valid interval" (defined in design Section 2) + timestamp-based dedup handle the duplication side. The word-loss side is handled by overlap: Whisper's in-chunk warm-up eats the first overlap, so the genuine stable content sits in the middle.
- **Sentence carryover stranding a never-terminated segment at chunk N−1.** If the final chunk's Whisper also ends without `.!?` (e.g., video cuts mid-word), the final buffer is flushed by the segmenter's end-of-stream path (already exists — `segment()` flushes any remaining buffer). Nothing additional needed; design Section 3 documents this as an explicit non-event.
- **Retry amplification cost.** Worst-case a 20-minute video spawns 5 chunks × 3 attempts = 15 Whisper calls. At typical chunk durations, that is ~300s of additional Whisper compute per retry-heavy job. Mitigation: retries are per-chunk bounded (2 retries, not 2×2=4 across job scope); and failed job still retains partial segments so the user gets some value from the wasted spend.
- **`SubtitleResponse` shape drift.** Adding `status`, `progress`, `error_code`, `error_message` is additive; Phase 0 consumers (we have none outside our own frontend) would see new optional fields and ignore them. But the **Phase 0 `GET /{video_id}` returns 404 when processing; Phase 1b returns 200** — this is a behavior change, not just a shape change. Any external script that relied on 404 as the "still processing" sentinel breaks. Mitigation: we do not ship an external API yet (CORS pinned to localhost); document the change in archive.
- **`error_message` now leaves the log surface and enters the API surface.** Phase 0 stored raw exception strings in `jobs.error_message` because only logs consumed it. Phase 1b surfaces it to every `/subtitles/{video_id}` response, so leaking OpenAI request IDs or truncated API-key fragments becomes a real risk. Mitigation: Phase 1b introduces a sanitization layer (`_SAFE_MESSAGES` in `pipeline.py`, see `design.md` §5) that maps error codes to canonical user-facing Chinese strings; raw exceptions go to logs only. Tested by a regex assertion that no response body matches `sk-[A-Za-z0-9]` or `api.openai.com`.
- **Reprocess race during playback.** A user with `/watch/:videoId` open while the same `video_id` is resubmitted in another tab would otherwise see the player unmount mid-playback as `upsert_video_clear_segments` wipes the segments. Mitigation: `PlayerPage` installs a sticky-completed guard (design.md §7, invariant 7) — once `status=completed` is seen, the UI freezes on the completed layout for the rest of the page lifecycle. The backend behavior is unchanged; only the UI refuses to downgrade.
- **`publish_video` atomic replaces-all write path is being broken up.** Phase 0's design principle was "`publish_video` is the only sanctioned write path." Phase 1b splits it into `upsert_video_clear_segments` + `append_segments`. Mitigation: the new pair is still the only sanctioned write path; both live in `VideosRepo`; the atomic guarantee narrows from "all segments appear together" to "each chunk's segments appear together, and the sequence of chunks is monotone by `idx`." Design Section 6 documents the new invariant.
- **HomePage UX regression if `createJob` fails.** Currently the HomePage spinner surfaces a network error inline. With the "navigate immediately" flow, a failed `createJob` would still leave the user on HomePage (no navigation) — the existing error state suffices. Risk is minimal but explicit.

## Acceptance gates (Definition of Done)

- **TTFS (time-to-first-subtitle):** for a 20-minute English video, p50 ≤ 15s from `createJob` response to first segment visible in `SubtitlePanel`. ui-verifier measures this by listening for the `el:first-segment` CustomEvent dispatched once by `PlayerPage` on the render where `segments.length` first transitions from 0 to > 0 (invariant 9 in `design.md` §8).
- **Completion SLO:** 20-minute English video processes end-to-end in ≤ 3 minutes (p95 across 5 runs).
- **Sync precision bar preserved:** once `status === 'completed'` and the user presses play, sentence p95 ≤ 100ms and word p95 ≤ 150ms — unchanged from Phase 0. ui-verifier uses the `?measure=1` flow from Phase 1a.
- **API contract:**
  - `GET /subtitles/{video_id}` with no prior job → `404`.
  - `GET /subtitles/{video_id}` during `processing` (before chunk 0 completes) → `200` with `status="processing"`, `segments=[]`, `progress` 0–15.
  - `GET /subtitles/{video_id}` during `processing` (chunk M completed, M+1..N pending) → `200` with monotone segments by `idx`, `status="processing"`, strictly increasing `progress`.
  - `GET /subtitles/{video_id}` after `failed` with partial segments → `200` with `status="failed"`, `segments=[..partial..]`, `error_code` + `error_message` set.
  - `GET /subtitles/{video_id}` after `completed` → `200` with shape byte-compatible with Phase 0 (plus additive `status="completed"`, `progress=100`, `error_code=None`, `error_message=None`).
- **Frontend states:**
  - `HomePage` after `createJob`: no spinner, no polling — immediate `navigate('/watch/:videoId')`.
  - `PlayerPage` while `status==="processing"`: no `<VideoPlayer>` mounted; `<ProcessingPlaceholder>` shows progress %; `<SubtitlePanel>` appends as segments arrive; controls bar hidden.
  - `PlayerPage` while `status==="failed"` with partial: no player; placeholder shows error message + "回首頁" button; `<SubtitlePanel>` read-only.
  - `PlayerPage` while `status==="failed"` with zero segments: no player; error-only page with "回首頁".
  - `PlayerPage` while `status==="completed"`: full Phase 1a UI (player + loop + speed) mounted once, not re-mounted on subsequent poll ticks.
- `MAX_VIDEO_MINUTES=20` enforced by `probe_metadata`; videos longer → `PipelineError(VIDEO_TOO_LONG)` before chunking.
- Every new or modified file ≤ 200 LOC (Phase 0 rule carried forward).
- pytest green, vitest green, `npm run lint`, `npm run build` succeeds.
- ui-verifier produces `docs/ui-verification/phase1b-segment-streaming.md` with PASS on: TTFS p50, completion p95, sync precision p95 on completed, processing-state no-player, failed-with-partial fallback.
