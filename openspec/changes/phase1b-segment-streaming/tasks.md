# Phase 1b: Segment Streaming — Tasks

Ordering reflects the dependency graph below. Tasks marked "parallel-eligible" can be dispatched concurrently with other parallel-eligible tasks as long as their file sets are disjoint. Tasks marked "sequential" block the next stage until merged.

```
T01 (audio_chunking)        ─┐
T02 (sentence_carryover)    ─┼─→ T06 (Pipeline.run rewrite) ─┐
T03 (config + 20min guard)  ─┤                                │
T04 (repo split + view)     ─┴───────→ T07 (router rewrite) ──┤
T05 (schemas + 4 fields)    ─────────→ T07                    │
                                                              │
T05 ──→ T08 (api/subtitles.ts client)                         │
T08 ──→ T09 (useSubtitleStream hook)                          │
T10 (ProcessingPlaceholder) — independent                     │
T11 (HomePage simplify) — independent                         │
T09 AND T10 ──→ T12 (PlayerPage status branching)             │
                                                              │
T06, T07, T11, T12 all green ──────────────────→ T13 (integrator)
```

Parallel-eligible groups:
- **Group A (pure backend, no shared files):** T01, T02, T03, T04, T05.
- **Group B (pure frontend, no shared files):** T10, T11. T08 is parallel-eligible with Group A's T04/T05 only after T05 merges (it depends on the schema shape).
- **Sequential merge points:** T06 (waits on T01+T02+T03+T04), T07 (waits on T04+T05), T09 (waits on T08), T12 (waits on T09+T10).
- **Gate:** T13 waits on everything.

Legend:
- **Dependencies** = tasks that must be merged before this one can start.
- **Parallel-eligible with** = tasks that may run concurrently in a different implementer dispatch (no overlapping files).
- **Required agents** = must sign off. `tdd-implementer` is always required; `spec-reviewer` reviews every task at completion; `ui-verifier` gates at T13.

**Pre-flight check (applies to every task T01–T13):**
> tdd-implementer MUST verify `git branch --show-current` returns `change/phase1b-segment-streaming` before any file change. If on `main`, STOP and surface to parent; do not switch or commit.

**Commit message template (every task):**
> `<type>(<scope>): <subject>` per project convention. One task = one commit (a separate refactor sub-commit within the same task is allowed if needed).

**Single-file ceiling:** every file listed as touched in a task MUST remain ≤ 200 LOC after the task's changes. If an acceptance step would push a file over, split the task.

---

## T01 — `audio_chunking` pure module + tests

- **Pre-flight:** verify branch `change/phase1b-segment-streaming`.
- **Dependencies:** none
- **Parallel-eligible with:** T02, T03, T04, T05

**Red tests (write first, in `backend/tests/unit/test_audio_chunking.py`):**
- `test_compute_schedule_short_video_single_chunk` — `duration_sec=45` → single `ChunkSpec(chunk_idx=0, audio=[0, 45], valid=[0, 45], is_first=True, is_last=True)`.
- `test_compute_schedule_boundary_60s_still_single_chunk` — `duration_sec=60` → single chunk `[0, 60]`.
- `test_compute_schedule_two_chunks_between_60_and_120` — `duration_sec=90` → two chunks per spec in `pipeline-streaming.md`.
- `test_compute_schedule_20min_matches_five_chunk_table` — `duration_sec=1200` → five chunks matching the table in `design.md` §2.
- `test_compute_schedule_first_chunk_has_no_leading_overlap` — any multi-chunk schedule: first chunk's `audio_start_sec == 0`.
- `test_compute_schedule_last_chunk_audio_end_equals_duration` — any multi-chunk schedule: last chunk's `audio_end_sec == duration_sec`.
- `test_compute_schedule_is_pure` — same input called twice returns equal lists.
- `test_clip_keeps_word_that_straddles_valid_start` — `ChunkSpec(valid_start=60, valid_end=360)`, word `{start:59.5, end:60.4}` retained.
- `test_clip_keeps_word_that_straddles_valid_end` — `ChunkSpec(valid_start=60, valid_end=360)`, word `{start:359.5, end:360.6}` retained.
- `test_clip_drops_word_outside_both_bounds` — word fully outside either side dropped.
- `test_clip_empty_words_returns_empty`.

**Green implementation:**
- `backend/app/services/transcription/audio_chunking.py` (NEW) exports `ChunkSpec` (frozen dataclass), `compute_schedule(duration_sec: float) -> list[ChunkSpec]`, `clip_to_valid_interval(words, spec) -> list[Word]`, `extract_chunk(source_audio: Path, spec: ChunkSpec, out_dir: Path) -> Path`.
- Constants `FIRST_CHUNK_SEC=60`, `REST_CHUNK_SEC=300`, `OVERLAP_SEC=3` live in this module.
- `extract_chunk` uses `subprocess.run(["ffmpeg", "-y", "-ss", ..., "-to", ..., "-c", "copy", ..., "-i", source, out_path])` (exact arg order per `design.md` §2; `-c copy` avoids re-encoding). Output filename is `chunk_{idx:02d}.mp3`.
- `compute_schedule` handles: `duration_sec <= FIRST_CHUNK_SEC` → single chunk; `FIRST_CHUNK_SEC < duration_sec <= FIRST_CHUNK_SEC + REST_CHUNK_SEC` → two chunks; longer → 1 + ceil((duration − FIRST)/REST) chunks with overlap rules from §2.

**Refactor note:** if the schedule-computation cases grow beyond ~80 LOC, extract a private `_build_chunk(...)` helper to keep the public function readable.

- **Validates:** pipeline-streaming spec scenarios under "Chunk schedule" and "Overlap clipping".
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(pipeline): add audio_chunking schedule and clip helpers`

**Files touched**
- `backend/app/services/transcription/audio_chunking.py` (NEW, target ≤ 120 LOC)
- `backend/tests/unit/test_audio_chunking.py` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

**Decision (resolved):** trust ffmpeg's non-zero exit code. A failed `subprocess.run(..., check=True)` will raise `CalledProcessError` which bubbles as a non-retry-eligible error; no extra size-check wrapper needed. spec-reviewer may revisit if real-world ffmpeg flakiness later motivates defensive hardening.

---

## T02 — `sentence_carryover` pure module + tests

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T01, T03, T04, T05

**Red tests (write first, in `backend/tests/unit/test_sentence_carryover.py`):**
- `test_clean_terminator_returns_none_held` — `[{text_en: "Hi world."}]` → `(None, [input])`.
- `test_missing_terminator_returns_held` — `[{text_en: "hello there", words: [...]}]` → `(input, [])`.
- `test_mixed_last_open` — `[seg_ok, seg_ok, seg_open]` → `(seg_open, [seg_ok, seg_ok])`.
- `test_closing_quote_after_period_treated_as_terminated` — `[{text_en: 'She said "hi."'}]` → `(None, [input])`.
- `test_empty_list_returns_none_empty` — `[]` → `(None, [])`.
- `test_question_mark_terminator` — last char `?` → emitted.
- `test_exclamation_terminator` — last char `!` → emitted.
- `test_words_from_segment_returns_a_copy_not_reference` — mutating the returned list does not affect the segment dict.

**Green implementation:**
- `backend/app/services/alignment/sentence_carryover.py` (NEW) exports `split_last_open_sentence(segments) -> tuple[Optional[dict], list[dict]]` and `words_from_segment(seg) -> list[Word]`.
- Trailing-quote strip rule matches `segmenter.py`'s punctuation rule verbatim (closing `"`, `"`, `"`, `'`). Implementer MUST locate the equivalent rule in `segmenter.py` and import it if already exported, otherwise replicate it and leave a comment linking to the segmenter source-of-truth.

**Refactor note:** if `segmenter.py` already exposes a `_ends_with_terminator` helper, reuse it and delete the local copy.

- **Validates:** pipeline-streaming spec scenarios under "Sentence carryover".
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(alignment): add sentence_carryover split_last_open_sentence`

**Files touched**
- `backend/app/services/alignment/sentence_carryover.py` (NEW, target ≤ 60 LOC)
- `backend/tests/unit/test_sentence_carryover.py` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

**Decision (resolved):** implementer's judgment during TDD. Default path: replicate the 2-line predicate inline in `sentence_carryover.py` with a comment linking to `segmenter.py` as the source-of-truth. If during green-phase the predicate feels duplicated or grows beyond a trivial one-liner, extract to a shared helper at that point (refactor sub-commit allowed). spec-reviewer will confirm the final placement.

---

## T03 — Lower `MAX_VIDEO_MINUTES` to 20 + probe guard test

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T01, T02, T04, T05

**Red test (write first):**
- Extend `backend/tests/unit/test_youtube_audio.py` with `test_probe_raises_video_too_long_at_21_minutes` — a fake yt-dlp response with `duration == 21 * 60 + 1` seconds triggers `PipelineError("VIDEO_TOO_LONG", ...)`. A parallel case at `duration == 20 * 60` passes.

**Green implementation:**
- `backend/app/config.py` lowers `MAX_VIDEO_MINUTES` from `30` to `20`.
- `backend/app/services/transcription/youtube_audio.py` confirms the `probe_metadata` guard reads from `config.MAX_VIDEO_MINUTES` (no hardcoded `30`).

**Refactor note:** if any other module references `MAX_VIDEO_MINUTES`, they continue reading from `config.py` — no inlined constants.

- **Validates:** pipeline-streaming scenario "MAX_VIDEO_MINUTES enforced at 20".
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `chore(config): lower MAX_VIDEO_MINUTES to 20`

**Files touched**
- `backend/app/config.py`
- `backend/app/services/transcription/youtube_audio.py` (only if a hardcoded `30` is found)
- `backend/tests/unit/test_youtube_audio.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T04 — Repository split: `upsert_video_clear_segments` + `append_segments` + `get_video_view`, delete `publish_video`

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T01, T02, T03, T05

**Red tests (write first, in `backend/tests/unit/test_repositories_videos.py` — extend existing file):**
- `test_upsert_video_clear_segments_creates_videos_row_and_clears_segments` — pre-seed a `videos` row + segments; call the method; assert videos row upserted and segments deleted, all in one transaction.
- `test_upsert_is_idempotent_across_resubmission` — call twice with the same `video_id`; second call still succeeds and clears any new segments added between calls.
- `test_append_segments_atomic_per_chunk` — append a batch of 3 segments; assert all 3 exist; inject a PK collision on the 2nd row and assert the batch rolls back (no row inserted).
- `test_append_segments_idx_collision_raises` — append with an `idx` that already exists → raises.
- `test_get_video_view_returns_none_when_no_job_exists`.
- `test_get_video_view_reads_latest_job_by_created_at` — two jobs for same video; latest wins.
- `test_get_video_view_reads_segments_ordered_by_idx`.
- `test_get_video_view_internal_consistency` — method executes in one transaction (can be asserted by spying on `conn.execute` and ensuring no intermediate `COMMIT`).
- Decision-table coverage (one assertion per row of the table in `design.md` §5 / `subtitles-api.md`).

**Red test (callers):**
- Search-and-replace for `publish_video` call sites in tests: the Phase 0 `test_pipeline_golden.py` will break; that's expected (it is rewritten in T06). Flag the break but don't fix in T04.

**Green implementation:**
- `backend/app/repositories/videos_repo.py` (MODIFIED):
  - Delete `publish_video`.
  - Add `upsert_video_clear_segments`, `append_segments`, `get_video_view` per signatures in `design.md` §6.
  - Reuse existing `DbConn` / connection handling; do not open new connections.
- File must remain ≤ 200 LOC. If the three new methods push it over, extract the decision-table shaping logic into a private `_view_row_to_dict` helper or move `get_video_view` into a separate reader module.

**Refactor note:** if decision-table branching exceeds ~50 LOC, extract it to `_assemble_view(jobs_row, videos_row, segments_rows) -> dict`.

- **Validates:** subtitles-api spec scenarios under "Repository".
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `refactor(repo): split publish_video into streaming-safe pair`

**Files touched**
- `backend/app/repositories/videos_repo.py`
- `backend/tests/unit/test_repositories_videos.py`

**Required agents**
- tdd-implementer
- spec-reviewer

**Decision (resolved):** align the outer view dict's key names exactly with `SubtitleResponse` pydantic field names (`video_id`, `status`, `progress`, `title`, `duration_sec`, `segments`, `error_code`, `error_message`) so the router body reduces to `SubtitleResponse(**view)`. For the inner `segments` list, keep the ORM dict keys (`start_sec`, `end_sec`, `words_json`, etc.) as the router already converts them to `Segment` pydantic; do not double-shape inside the repo.

---

## T05 — `SubtitleResponse` schema gains 4 fields

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T01, T02, T03, T04

**Red tests (write first, in `backend/tests/unit/test_schemas.py` — new file if missing, else extend):**
- `test_subtitle_response_completed_shape_byte_compatible_phase0` — construct a response with Phase 0 fields + the new fields (`status="completed"`, `progress=100`, `error_code=None`, `error_message=None`); assert that JSON-dumping and reading only the Phase 0 keys yields the Phase 0 bytes.
- `test_subtitle_response_processing_allows_null_title_and_duration` — `title=None, duration_sec=None, segments=[], status="processing"`; validates without error.
- `test_subtitle_response_failed_requires_error_fields` (or: `test_subtitle_response_failed_accepts_error_fields`) — `status="failed"` with `error_code="WHISPER_ERROR", error_message="..."` validates.
- `test_subtitle_response_rejects_unknown_status` — `status="done"` raises ValidationError.

**Green implementation:**
- `backend/app/models/schemas.py` (MODIFIED): update `SubtitleResponse` per `design.md` §5 — `title: Optional[str] = None`, `duration_sec: Optional[float] = None`, `status: Literal["queued","processing","completed","failed"]`, `progress: int`, `error_code: Optional[str] = None`, `error_message: Optional[str] = None`. Preserve field order so that Phase 0 field-order-dependent JSON consumers (if any) still work.

**Refactor note:** none expected — this is a schema-only addition.

- **Validates:** subtitles-api "Endpoint" response-shape scenarios.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(schemas): extend SubtitleResponse with status/progress/error`

**Files touched**
- `backend/app/models/schemas.py`
- `backend/tests/unit/test_schemas.py` (NEW if missing)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T06 — Rewrite `Pipeline.run` as per-chunk sequential loop

- **Pre-flight:** verify branch.
- **Dependencies:** T01, T02, T03, T04 (all merged)
- **Parallel-eligible with:** T05, T07, T08, T09, T10, T11 (no file overlap)

**Red tests (write first, in `backend/tests/integration/test_pipeline_streaming.py`, new file):**
- `test_five_chunk_happy_path_produces_monotone_segments` — fake whisper fixture yields chunk-tagged words for a 1200s fixture; pipeline runs; final `segments` ordered by `idx`, no duplicates, no gaps.
- `test_progress_advances_through_probe_download_chunks` — observe progress updates: probe→5, download→15, then `15 + (k+1)*85 // N` at each chunk k.
- `test_chunk_retry_twice_then_succeeds` — fake whisper raises `WhisperTransientError` on attempts 1-2 for chunk 2, succeeds on attempt 3; job completes; all segments appended.
- `test_chunk_three_failures_marks_job_failed_with_partial` — fake whisper raises `WhisperTransientError` three times on chunk 3; job ends `failed` with `error_code="WHISPER_ERROR"`; segments from chunks 0-2 remain in DB.
- `test_non_retry_eligible_error_bubbles_on_first_occurrence` — fake whisper raises an HTTP-4xx-non-429 on chunk 1; pipeline fails immediately (no retry delay).
- `test_sentence_held_across_boundary_preserves_original_timestamps` — fake whisper emits an open sentence at end of chunk 0, terminator at start of chunk 1; final segment's word timestamps come from chunk 0's emission.
- `test_no_duplicate_word_at_chunk_boundary` — word with `start=59.8, end=60.3`; appears in exactly one DB row after pipeline.
- `test_end_of_stream_flushes_unterminated_final_sentence` — final chunk's words end without `.!?`; pipeline still appends the tail via `segment()` end-of-stream path.
- `test_video_too_long_raises_before_download` — 21-minute fixture; no download is performed.
- `test_audio_files_deleted_on_completed_and_on_failed` — assert cleanup on both terminal states.
- `test_pipeline_single_chunk_for_short_video` — 45s fixture; exactly one chunk loop iteration.

**Red tests (existing coverage that must keep passing — migrate):**
- `test_pipeline_golden.py` and `test_pipeline_failures.py` (Phase 0) — rewrite assertions that hit `publish_video` to hit the new pair; keep end-to-end golden assertions intact.

**Green implementation:**
- `backend/app/services/pipeline.py` (REWRITTEN) follows the pseudocode in `design.md` §3 exactly:
  1. `probe_metadata` (progress=5; VIDEO_TOO_LONG raised here).
  2. `upsert_video_clear_segments(video_id, meta)`.
  3. `download_audio` (progress=15).
  4. `specs = compute_schedule(duration_sec)`.
  5. `carryover_buffer: list[Word] = []`; `next_segment_idx = 0`.
  6. For each `spec` in `specs`: attempt Whisper up to 3 times with 1s/2s backoff on `WhisperTransientError`; on success, `clip_to_valid_interval`, combine with carryover, `segment`, `split_last_open_sentence`, `translate_batch` on emitted only, assign monotone `idx`, `append_segments`, update progress via `_compute_progress(chunk_idx, total)`; on exhausted retries raise `PipelineError("WHISPER_ERROR", ...)`.
  7. After loop: if `carryover_buffer` non-empty, `segment` + `translate_batch` + `append_segments` the tail.
  8. `mark_job_completed`; delete audio files unconditionally.
- `_compute_progress(chunk_idx, total_chunks) -> int` is a private helper on the pipeline module: `return 15 + (chunk_idx + 1) * 85 // total_chunks`.
- File must remain ≤ 200 LOC. If the loop body exceeds reasonable size, extract `_process_chunk(spec, ctx) -> tuple[list[Segment], list[Word]]` into the same module.

**Refactor note:** ensure `Pipeline.run` itself (top-level) stays readable; move retry logic into a `_transcribe_with_retry(spec, audio_dir)` private helper if it crosses ~20 LOC inline.

- **Validates:** all pipeline-streaming spec scenarios under "Pipeline".
- **Sequential vs parallel:** sequential (merge point after Group A).
- **Suggested commit:** `refactor(pipeline): per-chunk streaming with carryover and retry`

**Files touched**
- `backend/app/services/pipeline.py`
- `backend/tests/integration/test_pipeline_streaming.py` (NEW)
- `backend/tests/integration/test_pipeline_golden.py` (assertions migrated to new repo pair)
- `backend/tests/integration/test_pipeline_failures.py` (same)

**Required agents**
- tdd-implementer
- spec-reviewer

**Decision (resolved):** option (a) — `whisper.py` is the classification site. T06's scope officially includes:
1. Define `WhisperTransientError(Exception)` in `backend/app/services/transcription/whisper.py`.
2. Inside `WhisperClient.transcribe`, wrap the `client.audio.transcriptions.create(...)` call in `try/except`; re-raise as `WhisperTransientError` when the underlying exception is any of: `openai.APIConnectionError`, `openai.APITimeoutError`, `openai.RateLimitError` (HTTP 429), or an `openai.APIStatusError` with `status_code >= 500`.
3. Any other exception (HTTP 4xx non-429, bad audio path, ffmpeg-not-found raised during audio open, etc.) re-raises as-is and is non-retry-eligible at the pipeline layer.
4. Add unit tests in `backend/tests/unit/test_whisper_client.py` (NEW if missing): one case per transient error class asserting `WhisperTransientError` is raised; one case for a 400 asserting the original exception passes through.

Files touched (updated): also add `backend/app/services/transcription/whisper.py` and `backend/tests/unit/test_whisper_client.py`.

---

## T07 — Rewrite `routers/subtitles.py` `GET /{video_id}` on the new view

- **Pre-flight:** verify branch.
- **Dependencies:** T04, T05
- **Parallel-eligible with:** T06, T08, T09, T10, T11 (no file overlap)

**Red tests (write first, in `backend/tests/integration/test_subtitles_router_streaming.py`, new file):**
- One assertion per row of the decision table in `subtitles-api.md` (9 rows):
  - no job → 404
  - queued + no video row + no segments → 200 queued
  - processing + no video row → 200 processing + empty segments
  - processing + video row + no segments → 200 processing + title/duration + empty segments
  - processing + video row + partial segments → 200 processing + partial segments
  - completed + video row + all segments → 200 completed byte-compat with Phase 0
  - failed + video row + partial → 200 failed + partial segments + error fields
  - failed + video row + no segments → 200 failed + empty segments + error fields
  - failed + no video row → 200 failed + nulls + error fields
- `test_router_returns_latest_job_on_resubmission`.
- `test_router_preserves_segment_order_by_idx`.
- `test_completed_shape_is_byte_compatible_phase0` — explicit comparison against a Phase 0 golden JSON fixture.

**Green implementation:**
- `backend/app/routers/subtitles.py` (MODIFIED): `GET /{video_id}` calls `VideosRepo(conn).get_video_view(video_id)`; `None` → `HTTPException(404, {"error_code":"NOT_FOUND", ...})`; otherwise construct `SubtitleResponse(**view)`.
- Keep `GET /api/subtitles/jobs/{job_id}` unchanged (design §5: "No endpoint removal").

**Refactor note:** the existing Phase 0 `GET /{video_id}` body becomes trivially short (two lines). If any Phase 0 helper becomes dead, delete it in a second commit within this task.

- **Validates:** subtitles-api "Endpoint" spec scenarios.
- **Sequential vs parallel:** sequential after T04+T05; parallel with T06.
- **Suggested commit:** `refactor(router): serve live subtitles view on GET /{video_id}`

**Files touched**
- `backend/app/routers/subtitles.py`
- `backend/tests/integration/test_subtitles_router_streaming.py` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T08 — Frontend `api/subtitles.ts` client matches new response shape

- **Pre-flight:** verify branch.
- **Dependencies:** T05 (schema settled)
- **Parallel-eligible with:** T06, T07, T10, T11

**Red tests (write first, in `frontend/src/api/subtitles.test.ts` — extend existing):**
- `test_get_subtitles_parses_completed_shape` — mocked response with all fields including `status="completed"`, `progress=100`, segments present → typed return value has the fields.
- `test_get_subtitles_parses_processing_shape` — `status="processing"`, `progress=32`, `segments=[...partial...]`, `title` present, `error_code=null`, `error_message=null`.
- `test_get_subtitles_parses_failed_shape` — `status="failed"`, error fields populated.
- `test_get_subtitles_parses_queued_shape_with_nulls` — `status="queued"`, `title=null`, `duration_sec=null`, `segments=[]`.
- `test_get_subtitles_404_surfaces_error` — `HTTP 404` response throws an error that callers can distinguish from a 5xx.

**Green implementation:**
- `frontend/src/api/subtitles.ts` (MODIFIED): update the TypeScript `SubtitleResponse` type to mirror the backend pydantic shape (add `status`, `progress`, `error_code?`, `error_message?`; make `title` and `duration_sec` `string | null` / `number | null`). The `getSubtitles(videoId)` function returns the parsed body on 200 and throws on non-200.

**Refactor note:** keep fetch/JSON handling shared with the existing `createJob` call (DRY through existing `base.ts` if present).

- **Validates:** player-streaming-ui "useSubtitleStream: updates data on each successful response" (indirect — client shape is the contract).
- **Sequential vs parallel:** parallel-eligible with T06/T07/T10/T11.
- **Suggested commit:** `feat(api): extend SubtitleResponse types for streaming`

**Files touched**
- `frontend/src/api/subtitles.ts`
- `frontend/src/api/subtitles.test.ts`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T09 — `useSubtitleStream` hook + tests

- **Pre-flight:** verify branch.
- **Dependencies:** T08
- **Parallel-eligible with:** T06, T07, T10, T11

**Red tests (write first, in `frontend/src/features/player/hooks/useSubtitleStream.test.ts`):**
- `test_initial_fetch_fires_synchronously_on_mount` — mount with `videoId="abc"`; assert one `getSubtitles` call fires within the same tick.
- `test_polls_every_1000ms` — advance fake timers by 3001ms; assert 4 total fetches (1 initial + 3 ticks).
- `test_updates_data_on_response` — mock `getSubtitles` to return sequence A→B→C; observe `data` transitions.
- `test_cleans_up_interval_on_unmount` — unmount; advance timers; no further fetches.
- `test_null_video_id_is_inert` — mount with `null`; no fetches, no interval.
- `test_in_flight_fetch_discarded_after_unmount` — slow-response mock; unmount before it resolves; no state update fired.
- `test_transient_error_surfaces_but_does_not_stop_polling` — mock rejects once, then resolves; assert `error` populated then cleared (or `data` updated regardless).
- `test_videoId_change_restarts_polling` — prop changes from `"a"` to `"b"`; old interval cleared; new initial fetch fires.

**Green implementation:**
- `frontend/src/features/player/hooks/useSubtitleStream.ts` (NEW) implements per `design.md` §7:
  - Signature `(videoId: string | null) => { data, error }`.
  - `useEffect(... [videoId])`: immediate first fetch, then `setInterval(tick, 1000)`.
  - `cancelled` flag to prevent state-after-unmount.
  - Cleanup: `cancelled = true; clearInterval(id)`.
- File ≤ 80 LOC.

**Refactor note:** none expected — small hook.

- **Validates:** player-streaming-ui "useSubtitleStream" spec scenarios.
- **Sequential vs parallel:** sequential after T08; parallel with T06/T07/T10/T11.
- **Suggested commit:** `feat(player): add useSubtitleStream hook`

**Files touched**
- `frontend/src/features/player/hooks/useSubtitleStream.ts` (NEW)
- `frontend/src/features/player/hooks/useSubtitleStream.test.ts` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T10 — `ProcessingPlaceholder` component + tests

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T06, T07, T08, T09, T11

**Red tests (write first, in `frontend/src/features/player/components/ProcessingPlaceholder.test.tsx`):**
- `test_renders_progress_bar_and_percentage_text` — `progress=32` → bar style width `32%`, label text "處理字幕中 (32%)".
- `test_renders_title_when_provided` — `title="How to build"` rendered (truncated class applied).
- `test_renders_error_state_with_button` — `error="Whisper transient timeout"` → "處理失敗" heading, error message, "回首頁" button.
- `test_error_hides_progress_bar` — when error is set, no progress bar element rendered.
- `test_nohp_button_navigates_home` — click "回首頁" → `useNavigate` called with `'/'`.
- `test_progress_0_renders_a_zero_width_bar`.
- `test_progress_100_renders_a_full_bar`.

**Green implementation:**
- `frontend/src/features/player/components/ProcessingPlaceholder.tsx` (NEW) matches the Tailwind structure in `design.md` §7. ≤ 60 LOC.

**Refactor note:** if the button-styling classes are repeated anywhere else in the project, consider extracting a shared class string; otherwise leave inline.

- **Validates:** player-streaming-ui "ProcessingPlaceholder" spec scenarios.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(player): add ProcessingPlaceholder component`

**Files touched**
- `frontend/src/features/player/components/ProcessingPlaceholder.tsx` (NEW)
- `frontend/src/features/player/components/ProcessingPlaceholder.test.tsx` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T11 — Simplify `HomePage.tsx`: drop polling, navigate immediately

- **Pre-flight:** verify branch.
- **Dependencies:** none (the PlayerPage handles post-navigate behavior; HomePage only needs to navigate)
- **Parallel-eligible with:** T06, T07, T08, T09, T10

**Red tests (write first, in `frontend/src/routes/HomePage.test.tsx`, new file):**
- `test_submit_success_navigates_to_watch_route_immediately` — mock `createJob` → `{ video_id: "abc", ... }`; click submit; assert `useNavigate` called with `/watch/abc` on the same tick (no intervening spinner render).
- `test_submit_does_not_render_loading_spinner_after_success`.
- `test_submit_does_not_start_job_polling` — no `useJobPolling` call (or no polling interval visible via fake timers).
- `test_submit_failure_keeps_user_on_homepage` — `createJob` rejects; `useNavigate` not called; inline error visible.
- `test_submit_failure_allows_retry` — after error, user edits URL and submits again; second attempt fires.
- `test_cache_hit_navigates_same_as_fresh_submit` — response with `status="completed"` from a cache-hit short-circuit still navigates (`PlayerPage` handles the `completed` branch on its first poll).

**Green implementation:**
- `frontend/src/routes/HomePage.tsx` (MODIFIED):
  - Drop imports of `useJobPolling`, `LoadingSpinner`, `progressText` logic, navigation `useEffect`.
  - Drop state: `jobId`, `pendingVideoId`.
  - Keep `loading` flag for the duration of the POST.
  - On `createJob` success: `navigate('/watch/${result.video_id}')` synchronously.
  - On error: existing inline error UI preserved.
- Target reduction: ~30 LOC.

**Refactor note:** If `useJobPolling` is no longer imported anywhere else, flag it for deletion in a follow-up cleanup task — do not delete in T11 (it is still the contract for the now-unused `GET /jobs/{job_id}` endpoint, and a separate change may remove both together).

- **Validates:** player-streaming-ui "HomePage" spec scenarios.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `refactor(home): navigate immediately after createJob`

**Files touched**
- `frontend/src/routes/HomePage.tsx`
- `frontend/src/routes/HomePage.test.tsx` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

**Decision (resolved):** leave `useJobPolling.ts` on disk untouched in T11. The `/jobs/{job_id}` endpoint remains; a later phase-closing simplify pass will decide whether to delete both together. T11 must only remove the *import* in `HomePage.tsx`; do not delete the hook file or its test file.

---

## T12 — `PlayerPage.tsx` status branching + mount-once guard

- **Pre-flight:** verify branch.
- **Dependencies:** T09, T10 (hook + placeholder both merged)
- **Parallel-eligible with:** none (this is the only task writing to `PlayerPage.tsx` in this batch; T06/T07/T11 do not touch it)

**Red tests (write first, in `frontend/src/routes/PlayerPage.streaming.test.tsx`, new file):**
- `test_null_data_renders_loading_spinner` — initial render, hook returns `{data: null}` → `<LoadingSpinner>` visible, no `<VideoPlayer>` in DOM.
- `test_queued_status_renders_processing_layout_no_player` — `data.status="queued"` → `ProcessingPlaceholder` with `progress=0`, no player.
- `test_processing_renders_placeholder_and_partial_subtitle_panel` — `status="processing"`, `progress=45`, some `segments` → placeholder shows 45%, `SubtitlePanel` lists segments, no player.
- `test_processing_appends_segments_between_polls_without_panel_remount` — two consecutive `data` values with K and K+M segments; assert `SubtitlePanel` renders K+M entries and the panel's React instance is preserved across updates.
- `test_failed_with_partial_renders_error_placeholder_and_readonly_panel` — `status="failed"`, `error_message` set, segments non-empty → placeholder in error mode; panel read-only.
- `test_failed_zero_segments_renders_error_only_page` — `status="failed"`, `segments=[]` → placeholder in error mode; panel area empty or absent.
- `test_hohp_button_navigates_home` — click the "回首頁" button in failed state → navigate to `/`.
- `test_completed_renders_full_phase1a_player` — `status="completed"` with full segments → `<VideoPlayer>` mounted, `<PlayerControls>` visible, loop/speed/keyboard wiring present.
- `test_player_mounts_exactly_once_across_processing_to_completed_transition` — scripted sequence `processing → processing → completed → completed` through the mock hook; spy on `<VideoPlayer>` mount callbacks; assert exactly one mount call.
- `test_completed_polls_do_not_remount_player` — subsequent polls after `completed` do not trigger additional mounts.
- `test_progress_observed_by_user_is_monotone` — scripted progress `[10, 25, 45, 100]`; each `ProcessingPlaceholder` render's text shows a value ≥ the previous.
- `test_measure_flag_preserved_through_completed_branch` — URL `?measure=1` + `status="completed"` → `computePlaybackFlags` call path unchanged from Phase 1a (auto-pause off, loop off).

**Red tests (existing coverage — must stay green):**
- `frontend/src/routes/PlayerPage.measure.test.tsx` — after T12, the test must still pass against the completed-branch code path. If the test references the old Phase 0 `GET /subtitles` 404-then-completed flow, the MSW handler is updated to return the new streaming shape with `status="completed"` on first poll.

**Green implementation:**
- `frontend/src/routes/PlayerPage.tsx` (MODIFIED) per `design.md` §7:
  - Top-level `const { data } = useSubtitleStream(videoId)`.
  - Branch on `data == null` → loading; `queued | processing` → `ProcessingLayout`; `failed` → `ProcessingLayout` with error; `completed` → `CompletedLayout`.
  - `ProcessingLayout` and `CompletedLayout` are defined as local components in `PlayerPage.tsx` (or extracted to sibling files if `PlayerPage.tsx` exceeds 200 LOC).
  - `CompletedLayout` contains the full Phase 1a tree: `<VideoPlayer>`, `<SubtitlePanel>` with highlight, `<PlayerControls>` with loop+speed+keyboard wiring.
  - The `?measure=1` read and `computePlaybackFlags` call happen inside `CompletedLayout` only.
- File ≤ 200 LOC. If it exceeds, extract `CompletedLayout` and/or `ProcessingLayout` into sibling files under `features/player/components/`.

**Refactor note:** this is the highest-risk file in the phase. Implementer should run the simplify pass after green to check for duplicated-code between layouts and consolidate before spec-reviewer enters.

- **Validates:** player-streaming-ui "PlayerPage" spec scenarios.
- **Sequential vs parallel:** sequential.
- **Suggested commit:** `refactor(player): branch PlayerPage on subtitle stream status`

**Files touched**
- `frontend/src/routes/PlayerPage.tsx`
- `frontend/src/routes/PlayerPage.streaming.test.tsx` (NEW)
- `frontend/src/routes/PlayerPage.measure.test.tsx` (MSW handler update only, if needed)
- (optional) `frontend/src/features/player/components/CompletedLayout.tsx`, `ProcessingLayout.tsx` (if splitting for LOC budget)

**Required agents**
- tdd-implementer
- spec-reviewer

**Decision (resolved):** start with inline local components (`ProcessingLayout` and `CompletedLayout` defined in the same file). If the green implementation pushes `PlayerPage.tsx` over the 200-LOC ceiling, extract `CompletedLayout` first (it holds the Phase 1a tree — the larger one), then `ProcessingLayout` if still over. Extracted files land at `frontend/src/features/player/components/{CompletedLayout,ProcessingLayout}.tsx`. The extraction can be a refactor sub-commit within T12.

---

## T13 — Integrator gate: full test sweep, lint, build, ui-verifier, PR

- **Pre-flight:** verify branch.
- **Dependencies:** T01–T12 all merged and green on their individual tests
- **Parallel-eligible with:** none

**Acceptance criteria**
- `cd backend && python -m pytest` green (all units + integrations, including new `test_audio_chunking.py`, `test_sentence_carryover.py`, `test_pipeline_streaming.py`, `test_subtitles_router_streaming.py`, migrated `test_pipeline_golden.py` and `test_pipeline_failures.py`, untouched `test_repositories_jobs.py`, `test_jobs_api.py`, etc.).
- `cd frontend && npx vitest run` green (all suites including `useSubtitleStream.test.ts`, `ProcessingPlaceholder.test.tsx`, `HomePage.test.tsx`, `PlayerPage.streaming.test.tsx`, untouched `useSubtitleSync.*`, `useLoopSegment.test.ts`, `usePlaybackRate.test.ts`, `useAutoPause.test.ts`, `useKeyboardShortcuts.test.ts`, `PlayerPage.measure.test.tsx`).
- `cd frontend && npm run lint` clean.
- `cd frontend && npm run build` succeeds.
- **200-line scan** — no `.py`/`.ts`/`.tsx` file over 200 lines across `backend/app` + `frontend/src`.
- ui-verifier agent boots real dev servers (backend on 8000, frontend on 5173), drives Playwright through the Phase 1b flows, and produces `docs/ui-verification/phase1b-segment-streaming.md` with PASS on:
  - **TTFS (time-to-first-subtitle).** For a 20-minute English video fixture, p50 ≤ 15s from `createJob` response to the first segment visible in `SubtitlePanel`. Report p50 and p95.
  - **Completion SLO.** 20-minute English video processes end-to-end in ≤ 3 minutes (p95 across 5 runs).
  - **Sync precision preserved on completed.** After `status="completed"` and the user presses play, sentence p95 ≤ 100ms and word p95 ≤ 150ms using the `?measure=1` flow from Phase 1a. This is a regression check, not a new metric.
  - **Processing state no-player.** While `status="processing"`, assert no `<iframe>` (YouTube player) exists in the DOM.
  - **Failed-with-partial fallback.** Drive a fixture that fails on chunk 3; assert placeholder renders with error + "回首頁" button, and the partial `SubtitlePanel` lists the chunks-0-2 segments.
  - **Navigate-immediately.** Submit on HomePage; assert URL transitions to `/watch/:videoId` within < 100ms of the `createJob` response and no spinner appears on HomePage after submit.
  - **Player mounts exactly once.** Spy on `<VideoPlayer>` mount callbacks across the full `queued → processing → completed` flow; assert exactly one mount.
- `openspec/archive/` and `openspec/changes/phase1b-segment-streaming/` are moved to archive per `AGENTS.md` convention (change directory stays in-tree; spec files are archived at phase close). Integrator moves the directory to `openspec/archive/phase1b-segment-streaming/` and updates `CLAUDE.md` phase roadmap to mark Phase 1b complete.
- PR opened against `main` with the archive move + ui-verifier report committed. PR title: `Phase 1b: Segment Streaming`. PR body includes: acceptance-gate table (TTFS, completion, sync, all ui-verifier PASS), pytest/vitest/lint/build result summary, link to `docs/ui-verification/phase1b-segment-streaming.md`.

**Files touched**
- `docs/ui-verification/phase1b-segment-streaming.md` (NEW)
- `openspec/archive/phase1b-segment-streaming/**` (moved from `openspec/changes/...`)
- `CLAUDE.md` (roadmap row for Phase 1b marked complete)

**Required agents**
- ui-verifier (final gate)
- integrator (archive move + PR)
- spec-reviewer (final sign-off)

**Suggested commit(s):**
- `docs(ui-verification): phase1b segment streaming report`
- `chore(archive): archive phase1b spec after integration`

---

## Open questions — all resolved

Every open question raised during spec-writer's first pass has been decided at the spec gate (before T01 starts). Decisions are recorded inline in the affected task's section; this summary is the pointer.

1. **T01 (ffmpeg output verification):** trust exit code.
2. **T02 (quote-strip rule placement):** default replicate with source-of-truth comment; extract during refactor if duplication grows.
3. **T04 (view dict shape):** align outer keys with `SubtitleResponse` pydantic fields; inner segment dicts stay ORM-shaped.
4. **T06 (`WhisperTransientError` site):** `whisper.py` is the classification site; T06 scope includes adding the class + unit tests.
5. **T11 (`useJobPolling.ts` deletion):** leave on disk; defer to a future simplify pass.
6. **T12 (layout extraction):** start inline; extract only if 200-LOC ceiling forces it.

No open questions remain for implementer dispatch. If spec-reviewer raises new ones during the spec review pass, append them here with their resolution before implementation begins.
