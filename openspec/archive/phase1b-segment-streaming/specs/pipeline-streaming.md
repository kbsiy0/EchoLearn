# Capability — Pipeline Streaming (Phase 1b)

## Responsibilities
- Transform the Phase 0 block-and-wait pipeline into a per-chunk streaming pipeline.
- Split a video's audio into an ordered schedule of 60s/300s chunks with 3s overlap, transcribe each chunk sequentially, and append its segments to the database immediately.
- Preserve sentence boundaries across chunk boundaries by holding any unterminated trailing segment and prepending it to the next chunk's word stream.
- Bound per-chunk Whisper failures with a retry policy; on exhausted retries, terminate the job while retaining already-appended segments.
- Advance `jobs.progress` monotonically so that polling observers see the job as alive throughout processing.

## Public interfaces

### Chunk schedule

```python
# backend/app/services/transcription/audio_chunking.py

@dataclass(frozen=True)
class ChunkSpec:
    chunk_idx:        int
    audio_start_sec:  float  # extract from here (includes leading overlap)
    audio_end_sec:    float  # extract to here (includes trailing overlap)
    valid_start_sec:  float  # words with end >= this are kept
    valid_end_sec:    float  # words with start <= this are kept
    is_first:         bool
    is_last:          bool

def compute_schedule(duration_sec: float) -> list[ChunkSpec]: ...
def extract_chunk(source_audio: Path, spec: ChunkSpec, out_dir: Path) -> Path: ...
def clip_to_valid_interval(words: list[Word], spec: ChunkSpec) -> list[Word]: ...
```

### Sentence carryover

```python
# backend/app/services/alignment/sentence_carryover.py

def split_last_open_sentence(
    segments: list[dict],
) -> tuple[Optional[dict], list[dict]]: ...

def words_from_segment(seg: dict) -> list[Word]: ...
```

### Pipeline

```python
# backend/app/services/pipeline.py
def run(job_id: str) -> None: ...
```

The `Pipeline.run` entrypoint signature is unchanged from Phase 0. Only the internal execution shape changes.

## Behavior scenarios

### Chunk schedule: short video fits in one chunk

GIVEN a video with `duration_sec == 45`
WHEN `compute_schedule(45)` is called
THEN the schedule is a single `ChunkSpec` with `chunk_idx=0`, `audio_start_sec=0`, `audio_end_sec=45`, `valid_start_sec=0`, `valid_end_sec=45`, `is_first=True`, `is_last=True`.

### Chunk schedule: boundary case at 60s

GIVEN a video with `duration_sec == 60`
WHEN `compute_schedule(60)` is called
THEN the schedule is a single chunk covering `[0, 60]` with `valid = [0, 60]`.

### Chunk schedule: two-chunk split between 60s and 120s

GIVEN a video with `duration_sec == 90`
WHEN `compute_schedule(90)` is called
THEN the schedule is two chunks:
- chunk 0: `audio=[0, 63]`, `valid=[0, 60]`, `is_first=True`, `is_last=False`
- chunk 1: `audio=[57, 90]`, `valid=[60, 90]`, `is_first=False`, `is_last=True`

### Chunk schedule: 20-minute video

GIVEN a video with `duration_sec == 1200`
WHEN `compute_schedule(1200)` is called
THEN the schedule has five chunks matching the table in `design.md` Section 2:
| chunk_idx | audio_start | audio_end | valid_start | valid_end |
|---|---|---|---|---|
| 0 | 0     | 63    | 0     | 60    |
| 1 | 57    | 363   | 60    | 360   |
| 2 | 357   | 663   | 360   | 660   |
| 3 | 657   | 963   | 660   | 960   |
| 4 | 957   | 1200  | 960   | 1200  |

AND the first chunk has `is_first=True, is_last=False`
AND the last chunk has `is_first=False, is_last=True` and `audio_end == duration`.

### Chunk schedule: rules are pure

GIVEN any non-negative `duration_sec`
WHEN `compute_schedule(duration_sec)` is called twice
THEN both calls return equal `ChunkSpec` lists (pure function; no hidden state).

### Overlap clipping: asymmetric partition rule

GIVEN a `ChunkSpec` with `valid_start_sec=60, valid_end_sec=360, is_first=False`
WHEN `clip_to_valid_interval` runs over a word stream
THEN a word is retained iff `w["start"] > valid_start_sec AND w["start"] <= valid_end_sec`.

GIVEN a `ChunkSpec` with `is_first=True`
WHEN clipping runs
THEN the `valid_start_sec` lower bound is relaxed: all words with `w["start"] <= valid_end_sec` are kept (including `start == 0`).

### Overlap clipping: word at the boundary belongs to the previous chunk

GIVEN a word `{start: 60.0, end: 60.4}`
AND a non-first `ChunkSpec` with `valid_start_sec=60, valid_end_sec=360`
WHEN `clip_to_valid_interval` runs
THEN the word is excluded (equality `start == valid_start_sec` is strict-`>`, so the word belongs to the previous chunk).

### Overlap clipping: word just after the boundary belongs to this chunk

GIVEN a word `{start: 60.01, end: 60.5}`
AND a non-first `ChunkSpec` with `valid_start_sec=60, valid_end_sec=360`
WHEN `clip_to_valid_interval` runs
THEN the word is retained.

### Overlap clipping: straddle at tail is retained

GIVEN a word `{start: 359.5, end: 360.6}` that spans the end-of-chunk boundary
AND a `ChunkSpec` with `valid_end_sec=360`
WHEN `clip_to_valid_interval` runs
THEN the word is retained (straddling at the tail is OK — the next chunk's strict-greater start rule prevents duplication).

### Overlap clipping: partition across consecutive chunks

GIVEN two adjacent `ChunkSpec`s with matched boundaries (`chunk0.valid_end == chunk1.valid_start`)
AND an input word stream covering both chunks' ranges
WHEN `clip_to_valid_interval` is applied to each chunk independently
THEN the union of the two clipped outputs equals the original input set (no drops, no duplicates) — `clip` is a partition over the input.

### Overlap clipping drops a word outside both bounds

GIVEN a `ChunkSpec` with `valid_start_sec=60, valid_end_sec=360`
AND a Whisper word with `start=361.0, end=361.5`
WHEN `clip_to_valid_interval` runs
THEN the word is excluded (its `start > valid_end_sec`).

### Timestamp offset: chunk-local to video-absolute

GIVEN a `ChunkSpec` with `audio_start_sec=57` extracted via `ffmpeg -ss 57 -to 363 ... -avoid_negative_ts make_zero`
AND Whisper returns a word at chunk-local `{start: 3.5, end: 3.9}`
WHEN the pipeline applies the offset
THEN the word's video-absolute timestamps are `{start: 60.5, end: 60.9}` before `clip_to_valid_interval` runs.

### Sentence carryover: clean terminator

GIVEN a segment list whose last element's `text_en` ends with a period, `?`, or `!` (after stripping trailing closing quotes)
WHEN `split_last_open_sentence(segments)` is called
THEN the result is `(None, segments)` — nothing held, full list emitted.

### Sentence carryover: missing terminator

GIVEN a segment list whose last element's `text_en` ends with a non-terminator character (e.g., `"hello there"`)
WHEN `split_last_open_sentence(segments)` is called
THEN the result is `(last_segment, segments_without_last)` — the final segment is held and removed from the emit list.

### Sentence carryover: closing quote after terminator

GIVEN a segment whose `text_en` is `She said "hi."`
WHEN `split_last_open_sentence` is called
THEN the segment is treated as terminated (the rule strips trailing closing quotes before inspecting the last character), and the segment is emitted.

### Sentence carryover: empty list

GIVEN an empty segment list
WHEN `split_last_open_sentence([])` is called
THEN the result is `(None, [])`.

### Pipeline: happy path across multiple chunks

GIVEN a job whose video probes to `duration_sec == 1200` and all Whisper calls succeed on the first attempt
WHEN `Pipeline.run(job_id)` executes
THEN the pipeline performs, in order: `probe_metadata` → `upsert_video_clear_segments` → `download_audio` → `compute_schedule` → for each `ChunkSpec` in order: `extract_chunk` → `WhisperClient.transcribe` → `clip_to_valid_interval` → combine with carryover buffer → `segment` → `split_last_open_sentence` → `translate_batch` on emitted sentences → `append_segments` → `update_progress`
AND after the last chunk loop iteration, any remaining carryover buffer is flushed through `segment` + `translate_batch` + `append_segments`
AND finally `mark_job_completed` runs and the audio files are deleted.

### Pipeline: translation skips held sentences

GIVEN a chunk whose final segment has no `.!?` terminator
WHEN the pipeline processes that chunk
THEN `translate_batch` is called only with the terminated (emitted) segments' `text_en`, not with the held segment.

### Pipeline: per-chunk retry on transient Whisper failure

GIVEN a pipeline run processing chunk M
AND the first `WhisperClient.transcribe` call raises `WhisperTransientError` without a `retry_after` attribute
WHEN the pipeline retries
THEN the pipeline sleeps 1s, retries; on a second transient failure it sleeps 2s, retries a third time; if the third attempt succeeds, processing of chunk M proceeds normally using that third result
AND no segments from chunk M are persisted until the successful attempt.

### Pipeline: Retry-After header is honored on 429

GIVEN a pipeline run processing chunk M
AND `WhisperClient.transcribe` raises `WhisperTransientError` with `retry_after=5`
WHEN the pipeline retries
THEN the pipeline sleeps exactly `min(5, 30) == 5` seconds (not the default 1s backoff) before the next attempt.

### Pipeline: Retry-After cap

GIVEN a `WhisperTransientError` with `retry_after=120`
WHEN the pipeline prepares to retry
THEN the pipeline sleeps `min(120, 30) == 30` seconds (capped).

### Pipeline: silent chunk does not crash segmenter

GIVEN a pipeline run where chunk M's Whisper result is empty (`raw_words == []`) AND the carryover buffer is also empty at the start of chunk M
WHEN the pipeline processes chunk M
THEN the pipeline MUST NOT call `segment([])` (which would raise `ValueError`)
AND no segments are appended for chunk M
AND progress is still advanced normally for chunk M
AND chunk M+1 proceeds as usual.

### Pipeline: silent chunk preserves carryover

GIVEN a pipeline run where chunk M's Whisper result is empty (`raw_words == []`) AND the carryover buffer at the start of chunk M is non-empty (from an open sentence at the end of chunk M−1)
WHEN the pipeline processes chunk M
THEN the carryover buffer is carried through to chunk M+1 intact (not discarded, not double-segmented).

### Pipeline: chunk directory is under data/audio with validated video_id

GIVEN any pipeline run for `video_id=V` (V regex-validated)
WHEN the pipeline extracts chunks
THEN the chunk files are written to `Path("data/audio") / f"chunks_{V}"`
AND that directory is deleted (recursively) on both terminal states (completed or failed), alongside the source audio file.

### Pipeline: error_message in API response is sanitized

GIVEN a pipeline run where `WhisperClient.transcribe` raises an exception whose `str()` contains a raw OpenAI URL or API-key fragment (e.g., `"Incorrect API key provided: sk-abcd1234..."`)
WHEN the pipeline handles the failure
THEN `jobs.error_message` is set to the canonical user-facing string from `_SAFE_MESSAGES[error_code]` (e.g., `"字幕轉錄失敗，請稍後再試"` for `WHISPER_ERROR`)
AND the raw exception text appears only in `logger.warning` records, never in the DB row or API response.

### Pipeline: three consecutive transient failures on a single chunk

GIVEN a pipeline run where three consecutive `WhisperClient.transcribe` calls on chunk M raise `WhisperTransientError`
WHEN the pipeline exhausts retries
THEN the pipeline raises `PipelineError("WHISPER_ERROR", ...)`, the job is marked `failed` with code `WHISPER_ERROR`
AND any segments already appended from chunks `0..M-1` remain in the database
AND the audio files are deleted.

### Pipeline: non-retry-eligible failure bubbles immediately

GIVEN a `WhisperClient.transcribe` call that raises a non-retry-eligible error (for example a local ffmpeg failure or an HTTP 4xx other than 429)
WHEN the pipeline encounters the error
THEN the pipeline does not retry; it raises `PipelineError` with the corresponding `error_code` on the first occurrence.

### Pipeline: sentence carryover preserves original timestamps

GIVEN chunk N ends with an open sentence whose words carry Whisper-assigned timestamps in the original audio timeline
WHEN chunk N+1 begins processing with the carryover buffer prepended
AND chunk N+1's Whisper output produces a terminator that closes that sentence
THEN the emitted segment's `start`, `end`, and per-word timestamps for the carried portion are the original chunk-N values, not chunk-N+1's re-transcription of the overlap region.

### Pipeline: end-of-stream flushes an unterminated final sentence

GIVEN a pipeline run where the last chunk's words end without a `.!?` terminator
WHEN the chunk loop completes
THEN the pipeline calls `segment(carryover_buffer)` once more, treats end-of-stream as a cut point, and appends the resulting segments
AND the final sentence is emitted as-is (matching Phase 0 end-of-audio behavior).

### Pipeline: progress is monotone

GIVEN any successful pipeline run with N chunks
WHEN the pipeline advances through probe, download, and each chunk
THEN `jobs.progress` updates are monotone non-decreasing, bounded `[0, 100]`, starting with probe at 5, download at 15, and each completed chunk k (0-indexed) advancing progress to `15 + (k + 1) * 85 // N`.

### Pipeline: progress update after failure is a no-op

GIVEN a job whose status has already transitioned to `failed` (or `completed`)
WHEN the pipeline (or any late-arriving helper) attempts `update_progress(job_id, value)`
THEN `JobsRepo.update_progress` MUST be a no-op: the SQL guard `WHERE job_id=? AND progress<=? AND status NOT IN ('failed','completed')` excludes the row
AND the row's `progress` column does not change.

### Pipeline: MAX_VIDEO_MINUTES enforced at 20

GIVEN a video whose `duration_sec / 60 > 20`
WHEN `probe_metadata` runs inside the pipeline
THEN the pipeline raises `PipelineError("VIDEO_TOO_LONG", ...)` before any chunking or download.

### Pipeline: short video runs a single-chunk loop

GIVEN a video with `duration_sec == 45`
WHEN the pipeline runs
THEN the schedule has one chunk, the loop iterates exactly once, no carryover can straddle a boundary (there is none), and the final flush may still emit the tail if the single chunk ends without a terminator.

## Invariants

1. **Sequential, not parallel.** Chunks run one at a time; `append_segments` is never called concurrently for the same `video_id`.
2. **Monotone reader prefix.** The segments returned by any `/subtitles/{video_id}` read at time t are a prefix (ordered by `idx`) of the segments returned at any later time t' for the same video.
3. **No duplicate words across boundaries.** `clip_to_valid_interval` partitions words across chunks by the asymmetric rule (`start > valid_start` AND `start <= valid_end`; first-chunk exception for `start == 0`). Each word belongs to exactly one chunk.
4. **Original timestamps for carried sentences.** Words carried via `sentence_carryover` retain their chunk-of-origin Whisper timestamps (already offset to video-absolute).
5. **Per-chunk retry bounded.** A single chunk attempts at most 3 Whisper calls; retries are per-chunk, not per-job.
6. **`Retry-After` header honored.** On `openai.RateLimitError`, the wrapper's `retry_after` attribute determines sleep duration (capped at 30s), not the default 1s/2s backoff.
7. **Partial retention on failure.** A `failed` pipeline run leaves previously-appended segments in the DB.
8. **Atomic per-chunk persistence.** Each `append_segments` call is one SQLite transaction; a chunk either fully lands or fully rolls back.
9. **Audio cleanup is unconditional.** Per-chunk extracted files AND the source download are deleted on every terminal state (completed or failed). The chunk directory at `data/audio/chunks_{video_id}` is removed recursively.
10. **Whisper is still the only time base.** Phase 1b does not introduce a second timing source; Phase 0's Section 3 invariant carries through. Chunk-local timestamps are offset by `spec.audio_start_sec` before entering the segmentation pipeline.
11. **`update_progress` is status-guarded.** The SQL guard prevents progress movement on `failed` or `completed` jobs; this defends the "no zombie progress" invariant under future concurrency.
12. **Silent chunks do not crash.** An empty Whisper result combined with an empty carryover buffer skips the `segment()` call; no `ValueError` escapes.
13. **Error messages are sanitized at the persistence boundary.** `jobs.error_message` never contains raw exception text; only `_SAFE_MESSAGES` canonical strings reach the DB and the API response.

## Non-goals (Phase 1b)

- Parallel chunk processing.
- SSE / WebSocket transport for progress or segments.
- Cancellation of in-flight jobs.
- Per-segment play gating (partial-range playback).
- Heuristic sentence detection beyond "last character in `.!?` (after stripping trailing closing quotes)".
- Relaxing `MAX_VIDEO_MINUTES` above 20.
- Schema change to the `segments` table.
- A `current_stage` string on `JobStatus` or `SubtitleResponse`.
- Word-level streaming (a sentence is still published only after its last word is transcribed).
- Any change to `useSubtitleSync` or its test suite.
