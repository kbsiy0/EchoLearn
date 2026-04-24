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

### Overlap clipping keeps a word that ends after valid_start

GIVEN a `ChunkSpec` with `valid_start_sec=60, valid_end_sec=360`
AND a Whisper word with `start=59.5, end=60.4`
WHEN `clip_to_valid_interval([...word...], spec)` is called
THEN the word is retained in the result (its `end >= valid_start_sec`).

### Overlap clipping drops a word outside both bounds

GIVEN a `ChunkSpec` with `valid_start_sec=60, valid_end_sec=360`
AND a Whisper word with `start=361.0, end=361.5`
WHEN `clip_to_valid_interval` runs
THEN the word is excluded (its `start > valid_end_sec`).

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
AND the first `WhisperClient.transcribe` call raises `WhisperTransientError`
WHEN the pipeline retries
THEN the pipeline sleeps 1s, retries; on a second transient failure it sleeps 2s, retries a third time; if the third attempt succeeds, processing of chunk M proceeds normally using that third result
AND no segments from chunk M are persisted until the successful attempt.

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

GIVEN a job whose status has already transitioned to `failed`
WHEN the pipeline (or any of its helpers) attempts `update_progress`
THEN the jobs_repo guards the call and the row's `progress` does not regress or advance.

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
3. **No duplicate words across boundaries.** A Whisper-detected word whose time span crosses a chunk boundary appears in the final DB exactly once.
4. **Original timestamps for carried sentences.** Words carried via `sentence_carryover` retain their original Whisper timestamps.
5. **Per-chunk retry bounded.** A single chunk attempts at most 3 Whisper calls; retries are per-chunk, not per-job.
6. **Partial retention on failure.** A `failed` pipeline run leaves previously-appended segments in the DB.
7. **Atomic per-chunk persistence.** Each `append_segments` call is one SQLite transaction; a chunk either fully lands or fully rolls back.
8. **Audio cleanup is unconditional.** Per-chunk extracted files and the source download are deleted on every terminal state (completed or failed).
9. **Whisper is still the only time base.** Phase 1b does not introduce a second timing source; Phase 0's Section 3 invariant carries through.

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
