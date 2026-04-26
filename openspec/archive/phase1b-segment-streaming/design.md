# Phase 1b: Segment Streaming — Design

Readers should be able to implement from this document alone.

---

## Section 1 — Architecture

```
backend/app/
  services/
    transcription/
      audio_chunking.py          (NEW — compute chunk schedule + ffmpeg cut)
      audio_chunking.test.py     (NEW)
      whisper.py                 (UNCHANGED — still per-call, receives chunk audio)
      youtube_audio.py           (MODIFIED — MAX_VIDEO_MINUTES 30→20 enforcement)
    alignment/
      segmenter.py               (UNCHANGED — same single-pass cutter)
      sentence_carryover.py      (NEW — split-and-hold last open sentence)
      sentence_carryover.test.py (NEW)
    pipeline.py                  (MODIFIED — per-chunk sequential loop; see §3)
  repositories/
    videos_repo.py               (MODIFIED — publish_video split into
                                   upsert_video_clear_segments +
                                   append_segments; see §6)
  routers/
    subtitles.py                 (MODIFIED — GET /{video_id} branches on job
                                   status; response shape gains 4 fields)
  models/
    schemas.py                   (MODIFIED — SubtitleResponse + 4 fields)
  config.py                      (MODIFIED — MAX_VIDEO_MINUTES 30→20)

frontend/src/
  api/
    subtitles.ts                 (MODIFIED — getSubtitles returns new shape;
                                   test file extended)
  features/player/
    components/
      ProcessingPlaceholder.tsx  (NEW — replaces player during processing/failed)
      ProcessingPlaceholder.test.tsx (NEW)
    hooks/
      useSubtitleStream.ts       (NEW — poll /subtitles, accumulate segments)
      useSubtitleStream.test.ts  (NEW)
  routes/
    HomePage.tsx                 (MODIFIED — drop useJobPolling, instant navigate)
    HomePage.test.tsx            (NEW — covers submit → navigate, error stays)
    PlayerPage.tsx               (MODIFIED — status branch; player mount guard)
    PlayerPage.measure.test.tsx  (MODIFIED — completed flow only; no regressions)
```

### Module boundaries

| Concern | Owner | Why |
|---|---|---|
| Chunk schedule (start/end/overlap per chunk) | `audio_chunking.compute_schedule()` | Pure function of duration → list[ChunkSpec]; fully unit-testable |
| Chunk audio extraction via ffmpeg | `audio_chunking.extract_chunk()` | Thin wrapper around subprocess; separable from schedule computation |
| Whisper call for one chunk | `WhisperClient.transcribe()` (unchanged) | No change: Whisper sees a normal audio file; chunking is invisible to it |
| Overlap clipping | `audio_chunking.clip_to_valid_interval()` | Pure function on word list + ChunkSpec → word list; unit-testable |
| Sentence carryover (hold & prepend) | `sentence_carryover` module | Stateless pure functions; `Pipeline` owns the carryover buffer |
| Per-chunk loop orchestration | `Pipeline.run()` | Single place for per-chunk sequence, retry, progress, persistence |
| Progress math | `Pipeline._compute_progress(chunk_idx, total_chunks)` | Private helper on Pipeline; monotone by construction |
| DB reads for `GET /subtitles` | `VideosRepo.get_video_view()` (NEW) | Single repo method aggregates video row + segments + latest job |
| DB writes during streaming | `VideosRepo.upsert_video_clear_segments()` + `append_segments()` | Split of Phase 0's `publish_video`; §6 documents migration |
| Response shape assembly | `routers/subtitles.py` | Thin router calls repo once, builds pydantic response |
| Frontend streaming read | `useSubtitleStream(videoId)` hook | Encapsulates 1s poll + accumulation + stop condition |
| Frontend state branching | `PlayerPage` | Only component that sees `status`; owns player-mount decision |

### Deleted or heavily rewritten

- `VideosRepo.publish_video()` — deleted. Its call sites (Pipeline + tests) are migrated to the new pair. No backward-compat shim; repositories is an internal boundary.

---

## Section 2 — Chunking mechanism

### Chunk schedule

```python
FIRST_CHUNK_SEC = 60     # drives TTFS
REST_CHUNK_SEC  = 300    # amortize per-chunk overhead
OVERLAP_SEC     = 3      # edge tolerance for Whisper
```

`compute_schedule(duration_sec: float) -> list[ChunkSpec]` returns:

```python
@dataclass(frozen=True)
class ChunkSpec:
    chunk_idx:        int       # 0..N-1
    audio_start_sec:  float     # extract from here (includes leading overlap)
    audio_end_sec:    float     # extract to here (includes trailing overlap)
    valid_start_sec:  float     # words with end >= this are kept
    valid_end_sec:    float     # words with start <= this are kept
    is_first:         bool
    is_last:          bool
```

For a 1200s video the schedule is:

| chunk_idx | audio_start | audio_end | valid_start | valid_end |
|---|---|---|---|---|
| 0 | 0     | 63    | 0     | 60    |
| 1 | 57    | 363   | 60    | 360   |
| 2 | 357   | 663   | 360   | 660   |
| 3 | 657   | 963   | 660   | 960   |
| 4 | 957   | 1200  | 960   | 1200  |

Rules (enforced by `compute_schedule`):
- `audio_start = max(0, valid_start − OVERLAP_SEC)`
- `audio_end = min(duration, valid_end + OVERLAP_SEC)`
- First chunk has no leading overlap (starts at `0`); last chunk has no trailing overlap (ends at `duration`).
- If `duration <= FIRST_CHUNK_SEC`, the schedule is a single chunk covering `[0, duration]` with `valid = [0, duration]`. No chunking for short videos — the pipeline still runs the "per-chunk" loop with N=1, and TTFS degrades to "whole-audio Whisper time" which is fine for < 60s inputs.
- If `duration` falls between 60s and 120s, schedule is two chunks: `[0, 63]` + `[57, duration]`.

### Chunk extraction

```python
def extract_chunk(source_audio: Path, spec: ChunkSpec, out_dir: Path) -> Path:
    """Extract one chunk's audio slice. Canonical command:

    ffmpeg -y -ss {spec.audio_start_sec} -to {spec.audio_end_sec}
           -i {source_audio} -c copy -avoid_negative_ts make_zero {out_path}

    Flag rationale:
    - `-ss` before `-i`: fast input-seek.
    - `-to` (absolute end time) instead of `-t` (duration): the audio_end is
      already absolute; -t would re-derive it and risk off-by-frame drift.
    - `-c copy`: no re-encoding; preserves audio byte-accurately for Whisper.
    - `-avoid_negative_ts make_zero`: forces the output's t=0 to align with
      audio_start_sec. Without this, mp3 frame-boundary snapping of `-ss`
      would shift the output's reported t=0 by up to ~26ms (one frame at
      common bitrates). With it, word `start`/`end` values reported by
      Whisper can be safely offset as `spec.audio_start_sec + whisper_t`
      to recover the original video timeline.
    """
```

- Output filename is `chunk_{idx:02d}.mp3` so retry can overwrite idempotently.
- **`out_dir` is caller-provided and MUST be a trusted path.** `extract_chunk` does NOT validate the path. The pipeline's canonical `out_dir` is `Path("data/audio") / f"chunks_{video_id}"` where `video_id` is regex-validated in `videos_repo._validate_video_id`.
- Implementation uses `subprocess.run(..., check=True)`; a non-zero ffmpeg exit raises `CalledProcessError`, which bubbles up as a non-retry-eligible failure at the pipeline layer.

### Overlap clipping

After Whisper returns `words: list[Word]` for a chunk (with timestamps already offset from chunk-local to video-absolute), apply:

```python
def clip_to_valid_interval(words: list[Word], spec: ChunkSpec) -> list[Word]:
    # Asymmetric boundary: words BELONG to exactly one chunk.
    # Non-first chunks exclude words whose start is at or before valid_start
    # (those belong to the previous chunk). First chunk keeps everything
    # from t=0.
    def in_valid(w):
        start_ok = True if spec.is_first else w["start"] > spec.valid_start_sec
        end_ok   = w["start"] <= spec.valid_end_sec  # straddle at tail is OK
        return start_ok and end_ok
    return [w for w in words if in_valid(w)]
```

**The rule, stated plainly:**

- A word is assigned to the earliest chunk whose `valid_start_sec < w["start"] <= valid_end_sec`.
- First chunk: words with `w["start"] <= valid_end_sec` are kept (including the word at `start=0`).
- All later chunks: a word is kept only if `w["start"] > valid_start_sec` — i.e., words whose start lies *strictly after* the boundary. Equality goes to the previous chunk.

**Why asymmetric rather than symmetric:** a symmetric rule (`>=` on both sides) lets a boundary-terminating sentence emit the terminal word in *both* chunks — `world.` at `[59.8, 60.3]` ending a sentence, chunk 0 emits and chunk 1 re-emits (the sentence already terminated, so sentence carryover cannot dedupe). The asymmetric rule makes chunk-assignment a partition: every word belongs to exactly one chunk, regardless of whether the word terminates a sentence or straddles the boundary.

**Consequence for carryover:** when chunk 0 ends with an open sentence, its trailing words are kept (they satisfy `start <= valid_end_sec`) and flow into the carryover buffer. Chunk 1's Whisper re-transcribes `[valid_start − 3, valid_start]` as overlap-warm-up; those re-transcribed words have `start <= valid_start` and are excluded from chunk 1. The carried-buffer words then lead chunk 1's segmentation input. No duplicate. No carryover-sentence timestamp drift (the kept words are from chunk 0's Whisper, which saw them clean).

---

## Section 3 — Pipeline execution model

### Phase 0 baseline

```
probe → download → whisper (one call) → segment → translate_batch → publish_video → done
```

### Phase 1b

```
probe [progress=5]
    duration_sec > MAX_VIDEO_MINUTES * 60  →  PipelineError(VIDEO_TOO_LONG)
upsert_video_clear_segments(video_id, meta)
download [progress=15]
chunk_dir = Path("data/audio") / f"chunks_{video_id}"  # video_id regex-validated
compute_schedule(duration_sec)  →  specs: list[ChunkSpec]
carryover_buffer: list[Word] = []
next_segment_idx: int = 0
for spec in specs:
    for attempt in range(3):
        try:
            chunk_path = extract_chunk(source_audio, spec, chunk_dir)
            raw_words_local = whisper.transcribe(chunk_path)
            # Offset chunk-local timestamps to video-absolute before clipping.
            raw_words = [
                {**w, "start": w["start"] + spec.audio_start_sec,
                      "end":   w["end"]   + spec.audio_start_sec}
                for w in raw_words_local
            ]
            clipped    = clip_to_valid_interval(raw_words, spec)
            break
        except WhisperTransientError as e:
            if attempt == 2:
                raise PipelineError("WHISPER_ERROR", ...)
            # Honor OpenAI's Retry-After on rate-limit errors.
            retry_after = getattr(e, "retry_after", None)
            if retry_after is not None:
                sleep(min(retry_after, 30))
            else:
                sleep([1, 2][attempt])
    combined = carryover_buffer + clipped
    if combined:                                # silent-chunk guard
        segments     = segment(combined)
        held, emit   = split_last_open_sentence(segments)
        carryover_buffer = words_from_segment(held) if held else []
    else:                                       # Whisper returned empty, no carryover
        emit, carryover_buffer = [], []
    if emit:
        translated = translator.translate_batch([s["text_en"] for s in emit])
        for i, seg in enumerate(emit):
            seg["text_zh"] = translated[i]
            seg["idx"]     = next_segment_idx + i
        append_segments(video_id, emit)
        next_segment_idx += len(emit)
    update_progress(15 + (spec.chunk_idx + 1) * 85 // len(specs))

# Stream end: flush the final carryover (no next chunk to prepend it to)
if carryover_buffer:
    final_segs   = segment(carryover_buffer)
    translated   = translator.translate_batch([s["text_en"] for s in final_segs])
    for i, seg in enumerate(final_segs):
        seg["text_zh"] = translated[i]
        seg["idx"]     = next_segment_idx + i
    append_segments(video_id, final_segs)
    # Progress stays at 100 on single-chunk runs; flush appends without advancing.

mark_job_completed()
cleanup_audio_files_unconditionally(source_audio, chunk_dir)
```

### Why sequential (not parallel)

Brainstorming settled on Architecture A (sequential + DB-as-bus). This design inherits that:
- Chunks in order → segment `idx` assignment is trivial and monotone.
- No concurrent writes to the same video → `append_segments` does not need a lock.
- Total wall-clock for 20-minute video ≈ 15s probe/download + 5 chunks × ~15s/chunk = ~90s. Well under the 3-minute SLO.

### Retry policy

- **Per-chunk, bounded to 2 retries** (3 attempts total). Default backoff: 1s, 2s.
- Retry-eligible: network timeout, HTTP 5xx, OpenAI rate-limit (429). These raise `WhisperTransientError` in the client layer.
- **`Retry-After` header honored.** When the transient error is `openai.RateLimitError` and the exception carries a `retry_after` attribute (OpenAI sends it on 429), the pipeline sleeps `min(retry_after, 30)` seconds instead of the default backoff for that attempt. This avoids hammering into a still-rate-limited endpoint; the 30s cap bounds one chunk's total retry wait at ≤ 60s.
- Non-retry-eligible: HTTP 4xx other than 429 (misconfig, bad audio), local ffmpeg failure. These bubble up immediately.
- **Retry scope is one chunk, not the whole pipeline.** If chunk 2 succeeds but chunk 3 fails all 3 attempts, the job ends at `failed`; chunks 0–2's segments stay in the DB and the frontend reads them as partial. This implements brainstorming Q2=Z.

### Progress math

```python
def _compute_progress(chunk_idx: int, total_chunks: int) -> int:
    """probe=5, download=15, then linear over chunks to 100.

    After chunk 0 of 5: 15 + 1*85/5 = 32.
    After chunk 4 of 5: 15 + 5*85/5 = 100.
    """
    return 15 + (chunk_idx + 1) * 85 // total_chunks
```

Invariant: progress is monotone, integer, bounded `[0, 100]`. The `//` (floor division) guarantees the final chunk lands exactly at `100` when `85` is divisible by the count; for counts not dividing 85 cleanly, the last `update_progress` is followed by `update_status(completed)` which the frontend treats as "done regardless of progress", so the tiny rounding loss is invisible.

### Failure-path invariants

- On `PipelineError`: job → `failed`; a **sanitized** error message is written to `jobs.error_message` via `_SAFE_MESSAGES` (see Section 5 "Error sanitization"); the raw exception goes to `logger.warning` only; audio files deleted.
- **Already-appended segments stay in the DB** — this is the core promise of the "retain partial" brainstorming Q2=Z decision.
- On `update_progress` call after `failed`: the update MUST be a no-op. **T06 extends `JobsRepo.update_progress` to guard on status**: the SQL becomes `WHERE job_id=? AND progress<=? AND status NOT IN ('failed','completed')`. Phase 0's guard only enforced monotone progress; Phase 1b needs status-aware protection to defend the invariant under future concurrency.

---

## Section 4 — Sentence carryover

### Problem

A chunk's audio ends at `valid_end_sec`. A sentence spoken across the boundary looks like:

```
Chunk 0 words (last 3):  "... the quick brown"
Chunk 1 words (first 3): "fox jumped."
```

If we call `segment(chunk_0_words)` on its own, the segmenter sees `"... the quick brown"` with no terminator, hits end-of-stream, and flushes it as a malformed segment. Then `segment(chunk_1_words)` sees `"fox jumped."` and emits it — but the original sentence is now two ugly halves.

### Solution

Between chunks, hold the trailing open sentence and prepend it to the next chunk's word stream *before* segmenting.

```python
# sentence_carryover.py

def split_last_open_sentence(
    segments: list[dict]
) -> tuple[Optional[dict], list[dict]]:
    """If the last segment's text_en does not end with `.!?`, return
    (held_segment, emit_list_excluding_held). Otherwise (None, segments).

    A "segment ends with `.!?`" means: after stripping trailing closing quotes
    (", ", ", '), the last character is one of `.!?`. Matches segmenter.py's
    punctuation rule verbatim.
    """

def words_from_segment(seg: dict) -> list[Word]:
    """Extract the Word list from a segment dict."""
    return list(seg["words"])
```

**The held segment is not appended to the DB.** It is re-segmented next chunk as part of the combined buffer, which may produce a properly-terminated sentence (if chunk 2 contains the terminator) — in which case the carried-over words get their correct *original* timestamps, not chunk 1's boundary-warped ones.

**Last-chunk exception:** when `spec.is_last`, after the loop we flush `carryover_buffer` unconditionally via `segment()` which treats end-of-stream as a cut point. Any unterminated final sentence is emitted as-is (same as Phase 0's end-of-audio behavior).

### Non-heuristic choice

Brainstorming §2 Q1 decided: **no heuristic** beyond "last char in `.!?`". We do *not* try to detect "this dangling 'and' probably continues" or "this looks like a complete clause". Rationale: Whisper's output is already noisy near chunk edges; adding heuristic buffering compounds the errors. The overlap + carryover rule is sufficient for almost all cases; degenerate cases (mumbled sentences with no clear terminator for 30+ seconds) would produce weird output anyway.

### Tests for sentence_carryover

| Case | Input | Expected |
|---|---|---|
| Clean terminator | `[{text_en: "Hi world."}]` | `(None, [input])` |
| Missing terminator | `[{text_en: "hello there", words: [...]}]` | `(input, [])` |
| Mixed: last open | `[seg_ok, seg_ok, seg_open]` | `(seg_open, [seg_ok, seg_ok])` |
| Closing quote after period | `[{text_en: 'She said "hi."'}]` | `(None, [input])` (quote-stripped rule) |
| Empty list | `[]` | `(None, [])` |

---

## Section 5 — API contract

### Response shape

```python
# models/schemas.py

class SubtitleResponse(BaseModel):
    video_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int                    # 0..100
    title: Optional[str] = None      # unknown until probe completes
    duration_sec: Optional[float] = None
    segments: list[Segment]           # may be [] during queued/pre-first-chunk
    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

**Migration from Phase 0:** `title` and `duration_sec` become `Optional`. In `completed` state both are always non-null (behavior preserved). Consumers may assume `completed → title is not None`.

### Router logic

```python
# routers/subtitles.py

@router.get("/{video_id}", response_model=SubtitleResponse)
def get_subtitles(video_id: str, conn: DbConn) -> SubtitleResponse:
    view = VideosRepo(conn).get_video_view(video_id)
    if view is None:
        # No job for this video_id was ever submitted
        raise HTTPException(404, {"error_code": "NOT_FOUND", ...})
    return SubtitleResponse(**view)
```

### `get_video_view` decision table

| jobs row | videos row | segments | Response `status` | `progress` | `segments` | `title` |
|---|---|---|---|---|---|---|
| none | n/a | n/a | **404** | — | — | — |
| `queued` | none | none | `queued` | 0 | `[]` | `None` |
| `processing` | exists | some | `processing` | job.progress | all | videos.title |
| `processing` | exists | none | `processing` | job.progress | `[]` | videos.title |
| `processing` | none | none | `processing` | 0–5 | `[]` | `None` |
| `completed` | exists | all | `completed` | 100 | all | videos.title |
| `failed` | exists | some | `failed` | job.progress | some | videos.title |
| `failed` | exists | none | `failed` | job.progress | `[]` | videos.title |
| `failed` | none | none | `failed` | 0–5 | `[]` | `None` |

"Latest job" means `ORDER BY created_at DESC LIMIT 1` (existing index `idx_jobs_video` serves this).

### No endpoint removal

`GET /api/subtitles/jobs/{job_id}` stays. Useful for debugging, not used by the frontend after Phase 1b. Future cleanup could drop it; Phase 1b does not.

### Error sanitization

`jobs.error_message` is now surfaced in the API (it flows to `SubtitleResponse.error_message` on failed jobs). Before Phase 1b the field only leaked into logs. Phase 1b MUST sanitize before persisting:

```python
# backend/app/services/pipeline.py (module-level constant)
_SAFE_MESSAGES: dict[str, str] = {
    "VIDEO_TOO_LONG":    "影片超過 20 分鐘上限",
    "FFMPEG_MISSING":    "伺服器缺少 ffmpeg",
    "DOWNLOAD_ERROR":    "無法下載影片",
    "WHISPER_ERROR":     "字幕轉錄失敗，請稍後再試",
    "TRANSLATION_ERROR": "翻譯失敗，請稍後再試",
    "INTERNAL_ERROR":    "內部錯誤",
}
```

At every `update_status(job_id, "failed", error_code=..., error_message=...)` call site, `error_message` MUST be resolved via `_SAFE_MESSAGES[error_code]`. The original exception text goes to `logger.warning(...)` only. This prevents URL fragments, OpenAI request IDs, and truncated API-key fragments from reaching the response body. Test: `test_error_message_never_contains_api_key_or_url` asserts no API response body ever matches regex `/sk-[A-Za-z0-9]/` or `api\.openai\.com`.

---

## Section 6 — Repository changes

### Phase 0: `publish_video` (atomic all-or-nothing)

```python
def publish_video(video_id, title, duration_sec, source, segments):
    # single transaction:
    #   upsert videos row
    #   DELETE FROM segments WHERE video_id=?
    #   INSERT all segments
```

### Phase 1b: two atomic methods

```python
def upsert_video_clear_segments(
    self, video_id: str, title: str, duration_sec: float, source: str,
) -> None:
    """Called ONCE per pipeline run, after probe, before any chunk runs.

    Atomically:
      1. Upsert videos row (title/duration/source).
      2. DELETE FROM segments WHERE video_id=? (clean reprocess).

    This resets the partial-state: a re-submit for the same video_id wipes
    any stale segments before new chunks start appending. Also creates the
    videos row that subsequent append_segments calls rely on via FK.
    """

def append_segments(self, video_id: str, segments: list[dict]) -> None:
    """Called once per successful chunk in sequence.

    Atomically inserts the given segments. Caller is responsible for assigning
    monotone `idx` values that do not collide with already-appended segments.

    Raises on idx collision (relies on PK `(video_id, idx)`).
    """

def get_video_view(self, video_id: str) -> Optional[dict]:
    """Aggregate read: videos row + all segments + latest job.

    Returns None if no job ever existed for video_id. Otherwise returns a
    dict whose outer keys align exactly with SubtitleResponse pydantic field
    names, so the router body reduces to SubtitleResponse(**view). Inner
    `segments` list holds ORM dicts (keys `start_sec`, `end_sec`,
    `words_json`, etc.); the router converts them to `Segment` pydantic.

    Atomicity: the method MUST open an explicit
    `self._conn.execute('BEGIN DEFERRED')` before the three SELECTs and
    `self._conn.execute('COMMIT')` after. The connection factory at
    `db/connection.py` opens SQLite with Python's default
    `isolation_level=''` (legacy implicit auto-begin), so a sequence of
    SELECTs without an enclosing explicit transaction is NOT guaranteed
    to read a single snapshot — sqlite3 may auto-commit between
    statements, exposing torn state (e.g., `jobs.status='completed'` read
    first, but `segments` queried after a writer commits the last chunk).
    BEGIN DEFERRED takes a SHARED read lock for the duration of all
    three SELECTs; in WAL mode this does not block writers but DOES pin
    the snapshot. Test: `test_get_video_view_opens_begin_deferred` spies
    on `conn.execute` and asserts the exact sequence is BEGIN DEFERRED →
    3 SELECTs → COMMIT (5 calls total).
    """
```

### Why split Phase 0's `publish_video`

The atomic "all segments appear at once" contract of Phase 0 is genuinely incompatible with streaming — we *want* partial visibility. The split preserves atomicity per-chunk (a chunk either fully lands or fully rolls back on any INSERT error), and monotone `idx` guarantees the reader sees a prefix of the eventual final result at every poll.

### Invariants after the split

1. **Reader monotonicity.** `get_video_view(video_id).segments` at any moment is a prefix of the eventual final list (ordered by `idx`).
2. **No out-of-order writes.** `append_segments` is called by the pipeline in chunk order; the first call's segments have `idx` starting at `0`, the next starts at the previous's `len`.
3. **Clean reprocess.** Submitting the same `video_id` again causes `upsert_video_clear_segments` to wipe the segments table for that video before the new run's first append — the reader never sees a mix of old and new segments.
4. **FK integrity.** `segments.video_id` has `REFERENCES videos(video_id) ON DELETE CASCADE`, so we never have orphan segment rows.

### Callers migrated

- `Pipeline.run()` — rewritten per Section 3.
- Tests that asserted `publish_video` behavior are rewritten against the new pair. Fake pipeline tests continue to work because they inject `VideosRepo` or a fake that implements the new pair.

---

## Section 7 — Frontend changes

### `HomePage.tsx` — simplified

**Before:**
- holds `jobId` + `pendingVideoId` state
- polls with `useJobPolling`
- shows `<LoadingSpinner>` while processing
- navigates when `job.status === 'completed'`

**After:**
- drops `jobId`, `pendingVideoId`, `useJobPolling` import, `<LoadingSpinner>` import, `progressText` variable, the navigation `useEffect`
- keeps `loading` as a short-lived flag during the `createJob` POST
- on `createJob` success: `navigate('/watch/${result.video_id}')` synchronously — no polling
- on `createJob` error: same inline error display as today
- submits `cached=true` short-circuit behavior preserved

The file shrinks by roughly 30 lines.

### `PlayerPage.tsx` — state branching

```tsx
const { data } = useSubtitleStream(videoId);
// data: null | { status, progress, segments, title, duration_sec, error_code?, error_message? }

// Sticky-completed guard: once we've seen `completed` this page-lifetime, a
// later poll reverting to `processing`/`failed` (e.g., because the user
// resubmits the same video in another tab) must NOT unmount the player
// mid-playback. We freeze into completed view until page reload.
const sawCompletedRef = useRef(false);
if (data?.status === 'completed') sawCompletedRef.current = true;
const effectiveData = sawCompletedRef.current ? lastCompletedData : data;

if (effectiveData == null) return <LoadingSpinner progress={0} status="載入中..." />;

if (effectiveData.status === 'queued' || effectiveData.status === 'processing') {
  return (
    <ProcessingLayout
      progress={effectiveData.progress}
      segments={effectiveData.segments}
      title={effectiveData.title}
    />
  );
}

if (effectiveData.status === 'failed') {
  return (
    <ProcessingLayout
      progress={effectiveData.progress}
      segments={effectiveData.segments}
      title={effectiveData.title}
      error={effectiveData.error_message ?? '處理失敗'}
    />
  );
}

// effectiveData.status === 'completed'
return <CompletedLayout data={effectiveData} />;
```

**Implementation note on the sticky guard:** persist `lastCompletedData` with `useState` initialized to `null`; on every render where `data?.status === 'completed'`, `setState(data)`. Render `lastCompletedData` only after it has been populated at least once — otherwise fall through to normal `data`. The `sawCompletedRef` + `lastCompletedData` pair is ~5 LOC total.

**Loading-spinner cache-hit case:** when HomePage's `createJob` hits a cached video, the response `status` is already `completed`. On mount, `useSubtitleStream` fires the first fetch immediately (same tick), returns `status=completed` on the first poll, and the guard flips. The user sees `<LoadingSpinner>` for the single render between `data==null` and the first response — typically one frame. This is acceptable and documented.

- `ProcessingLayout` = left side `<ProcessingPlaceholder progress={...} error={...} />`, right side `<SubtitlePanel segments={data.segments} readOnly currentIndex={-1} currentWordIndex={-1} onClickSegment={() => {}} />`.
- `CompletedLayout` = exactly the Phase 1a layout (VideoPlayer + SubtitlePanel + PlayerControls).
- **Player mount guard:** `<VideoPlayer>` is rendered only inside `CompletedLayout`. React's component-tree mount rules ensure that on the `processing → completed` transition, the player mounts exactly once (when `ProcessingLayout` is swapped for `CompletedLayout`).

### `useSubtitleStream(videoId)` — new hook

```tsx
export function useSubtitleStream(videoId: string | null) {
  const [data, setData] = useState<SubtitleResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!videoId) return;
    let cancelled = false;
    let intervalId: number | null = null;

    const tick = async () => {
      try {
        const resp = await getSubtitles(videoId);  // 200 unless 404
        if (cancelled) return;
        setData(resp);
        // Terminal-state stop: once the job is done, stop polling to avoid
        // burning 1 req/s indefinitely on a tab left open overnight. The
        // response shape is stable after terminal so no UI staleness.
        if (resp.status === 'completed' || resp.status === 'failed') {
          if (intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
          }
        }
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message);
      }
    };
    tick();  // immediate first fetch
    intervalId = window.setInterval(tick, 1000);
    return () => {
      cancelled = true;
      if (intervalId !== null) clearInterval(intervalId);
    };
  }, [videoId]);

  return { data, error };
}
```

**TTFS instrumentation:** the hook does NOT dispatch the `el:first-segment` event; that responsibility belongs to `PlayerPage` (which owns the render). `PlayerPage` has a `useEffect([data?.segments.length])` that, on the first transition from 0 to >0 during processing state, dispatches `window.dispatchEvent(new CustomEvent('el:first-segment', { detail: { t: performance.now() } }))`. The ui-verifier Playwright script listens for this event and records `performance.now() - submit_time` as TTFS.

**Single-fetch-on-mount + 1s interval** is intentional: the component mounts, fires one request immediately (no 1-second blank), then polls. Matches the existing `useJobPolling` cadence and the brainstorming decision §3 Q2.

### `ProcessingPlaceholder.tsx`

```tsx
type Props = {
  progress: number;
  error?: string | null;
  title?: string | null;
};

export function ProcessingPlaceholder({ progress, error, title }: Props) {
  const navigate = useNavigate();
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
        <h3 className="text-red-400 text-lg">處理失敗</h3>
        <p className="text-gray-400 text-sm">{error}</p>
        <button
          onClick={() => navigate('/')}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg"
        >
          回首頁
        </button>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 p-8">
      {title && <p className="text-gray-400 text-sm truncate">{title}</p>}
      <div className="w-full max-w-sm">
        <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-500 transition-[width] duration-200"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
      <p className="text-gray-300 text-sm">處理字幕中 ({progress}%)</p>
    </div>
  );
}
```

Size stays under 50 LOC; single-responsibility.

### `SubtitlePanel.tsx` in processing mode

No code change to `SubtitlePanel` itself. The `processing` branch passes `currentIndex={-1}` and `currentWordIndex={-1}` so no highlight renders; `onClickSegment={() => {}}` disables click (but clicks have nothing to do — no player is mounted). These prop values are already handled by the component in the "subtitles empty / index out of range" path from Phase 0.

### Hook interaction with Phase 1a

`useSubtitleSync`, `useLoopSegment`, `usePlaybackRate`, `useAutoPause`, `useKeyboardShortcuts` all live inside `CompletedLayout`. They **only mount when `status === 'completed'`** — which means they see a stable, complete segments array on first run. No Phase 1a hook sees a growing segments array, so no Phase 1a invariant is stressed.

The `?measure=1` flow is unchanged: if the URL has `?measure=1` and the user loads a completed video, the completed-layout branch renders with the measure flag, which `computePlaybackFlags` consumes as before.

---

## Section 8 — Non-obvious invariants

Nine invariants, each one check-able against a test.

### 1. Monotone reader prefix

At any moment, the segments array returned by `GET /subtitles/{video_id}` is a prefix (by `idx` ordering) of the final completed segments array. Tested by: concurrent pytest that runs the pipeline on a fixture while polling and asserts each poll's segments is a prefix of the next.

### 2. No duplicate words across chunk boundaries

For any boundary between chunk N and chunk N+1, a Whisper-detected word whose time span crosses the boundary appears in the final DB exactly once. Tested by: fake whisper fixture emitting a contrived word at `[59.8, 60.3]`; after pipeline, `segments` contains it once.

### 3. Sentence carryover preserves original timestamps

A sentence held at chunk N and emitted after chunk N+1 has `start` / `end` / word timestamps from the **original** Whisper output, not from chunk N+1's re-Whispering of the overlap. Tested by: injection fake that tags Whisper output with chunk-origin metadata; assertion checks the final segment's origin is chunk-N for the carried portion.

### 4. Player mounts exactly once per page load

The `<VideoPlayer>` React component mounts when `status` transitions to `completed` and not before. Across the typical lifecycle (mount → processing-poll-loop → completed → mount player), the player mounts once. Tested by: Vitest render with a mock `useSubtitleStream` that cycles `processing → completed`; asserts the `VideoPlayer` mock sees exactly one `useEffect` mount callback.

### 5. Progress monotone

Every `/subtitles` poll's `data.progress` is `>=` the previous poll's progress for the same video. Tested by: MSW-backed Vitest test that runs a scripted `processing → completed` sequence and asserts monotone progress.

### 6. Failed job with zero segments still routes to `/` via click

When `status === 'failed'` and `segments.length === 0`, the UI shows error + "回首頁" button. Clicking navigates to `/`. Tested by: Vitest `userEvent.click` on the button.

### 7. Sticky-completed guard

Once `PlayerPage` has observed `data.status === 'completed'` in a given page lifecycle, subsequent polls returning `processing` or `failed` (possible on resubmit in another tab) MUST NOT cause the UI to re-render the processing / failed layout. The player stays mounted; playback position is preserved. Tested by: scripted hook mock cycling `completed → processing → failed`; assert the rendered tree stays `<CompletedLayout>` with a preserved React instance.

### 8. `update_progress` is status-guarded

`JobsRepo.update_progress(job_id, value)` MUST be a no-op when the job's current `status` is `failed` or `completed`. This is enforced at the SQL level: `WHERE job_id=? AND progress<=? AND status NOT IN ('failed','completed')`. Tested by: pytest marking a job failed, then calling `update_progress` with a higher value, asserting the row's progress column did not move.

### 9. TTFS event fires exactly once per page lifecycle

`PlayerPage` dispatches `window.dispatchEvent(new CustomEvent('el:first-segment', { detail: { t: performance.now() } }))` exactly once per mount — on the render where `data.segments.length` first transitions from 0 to > 0. Subsequent segment appends during the same `processing` session do NOT re-fire. A new page load starts the lifecycle over. Tested by: Vitest render with a scripted hook sequence `segments=[] → segments=[s0] → segments=[s0,s1]`; spy on `window.dispatchEvent` asserts exactly one call with type `el:first-segment`.

---

## Section 9 — Test layout

| Layer | New test files |
|---|---|
| Chunking | `audio_chunking.test.py` — `compute_schedule` cases (short, boundary, 20min); `clip_to_valid_interval` cases |
| Sentence carryover | `sentence_carryover.test.py` — cases table in §4 |
| Pipeline per-chunk | `test_pipeline_streaming.py` — 5 chunks happy path; chunk-2 retry-then-success; chunk-3 three-failures-then-failed-with-partial |
| Repo split | `test_videos_repo_streaming.py` — `upsert_video_clear_segments` + `append_segments` ordering; `get_video_view` decision table |
| Router | `test_subtitles_router_streaming.py` — decision table from §5 |
| Frontend stream | `useSubtitleStream.test.ts` — mount poll + interval + cleanup |
| Frontend page | `PlayerPage.streaming.test.tsx` — status branching; mount-once guard |
| Frontend home | `HomePage.test.tsx` — submit → navigate; no polling; error inline |
| Placeholder | `ProcessingPlaceholder.test.tsx` — progress render; error + nav |

Existing tests stay green:
- `useSubtitleSync` / `useAutoPause` / `useLoopSegment` / `usePlaybackRate`: untouched.
- `PlayerPage.measure.test.tsx`: still valid for the completed-layout path.
- `jobs.test.py` / `jobs_repo.test.py`: untouched.

---

## Section 10 — Out of scope (enforced by review)

The following are explicitly **not** in this change; a PR that includes them should be rejected or split:

- Parallel chunk processing.
- SSE / WebSocket transport for progress or segments.
- Cancellation of in-flight jobs.
- Per-segment play gating (partial-range playback).
- Any change to `useSubtitleSync` or its test suite.
- Any change to `?measure=1` semantics.
- Relaxing `MAX_VIDEO_MINUTES` above 20, or introducing a user-facing quota UI.
- Changing the `segments` table schema.
- A `current_stage` field on `JobStatus` or `SubtitleResponse`.
- Converting `useJobPolling` to use TanStack Query or similar (scope creep).
