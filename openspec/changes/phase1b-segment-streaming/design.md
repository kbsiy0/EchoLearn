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
    """ffmpeg -ss audio_start -to audio_end -c copy out_dir/chunk_{idx}.mp3"""
```

- `-c copy` avoids re-encoding (fast, byte-accurate for mp3 frame boundaries; good enough for Whisper).
- Output filename is `chunk_{idx:02d}.mp3` so retry can overwrite idempotently.

### Overlap clipping

After Whisper returns `words: list[Word]` for a chunk, apply:

```python
def clip_to_valid_interval(words: list[Word], spec: ChunkSpec) -> list[Word]:
    return [
        w for w in words
        if w["end"] >= spec.valid_start_sec and w["start"] <= spec.valid_end_sec
    ]
```

**Why `>=` and `<=` rather than strict:** a word that *crosses* the valid boundary is still content we want; we just don't want duplicates. The next-chunk or previous-chunk's valid interval will exclude the same word on its side (mirror-image clip), so net effect is one copy kept.

**Border case — word straddles two valid intervals:** a word with `start=59.5, end=60.4` qualifies for both chunk 0's `valid_end=60` (because `start=59.5 <= 60`) and chunk 1's `valid_start=60` (because `end=60.4 >= 60`). To avoid duplication, the rule resolves to **first writer wins**: chunk 0 emits it; chunk 1's segmenter receives a carryover buffer that already has this word (via sentence carryover, §4), so the duplicate is implicitly deduped by sentence grouping. We do not need an explicit dedup pass.

(In practice this is rare — Whisper tokenizes on word boundaries and rarely emits words that straddle a second-boundary by more than 100ms. The sentence carryover mechanism handles it as a side effect.)

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
compute_schedule(duration_sec)  →  specs: list[ChunkSpec]
carryover_buffer: list[Word] = []
next_segment_idx: int = 0
for spec in specs:
    for attempt in range(3):
        try:
            chunk_path = extract_chunk(audio, spec)
            raw_words  = whisper.transcribe(chunk_path)
            clipped    = clip_to_valid_interval(raw_words, spec)
            break
        except WhisperTransientError as e:
            if attempt == 2:
                raise PipelineError("WHISPER_ERROR", ...)
            sleep(backoff(attempt))  # 1s, 2s
    combined     = carryover_buffer + clipped
    segments     = segment(combined)
    held, emit   = split_last_open_sentence(segments)
    carryover_buffer = words_from_segment(held) if held else []
    translated   = translator.translate_batch([s["text_en"] for s in emit])
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

mark_job_completed()
delete_audio_files_unconditionally()
```

### Why sequential (not parallel)

Brainstorming settled on Architecture A (sequential + DB-as-bus). This design inherits that:
- Chunks in order → segment `idx` assignment is trivial and monotone.
- No concurrent writes to the same video → `append_segments` does not need a lock.
- Total wall-clock for 20-minute video ≈ 15s probe/download + 5 chunks × ~15s/chunk = ~90s. Well under the 3-minute SLO.

### Retry policy

- **Per-chunk, bounded to 2 retries** (3 attempts total). Backoff: 1s, 2s.
- Retry-eligible: network timeout, HTTP 5xx, OpenAI rate-limit (429). These raise `WhisperTransientError` in the client layer.
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

- On `PipelineError`: job → `failed` with error code/message; audio files deleted.
- **Already-appended segments stay in the DB** — this is the core promise of the "retain partial" brainstorming Q2=Z decision.
- On `update_progress` call after `failed`: the update is a no-op (jobs_repo already guards this via status check in Phase 0; we rely on the existing guard).

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
    dict shaped to SubtitleResponse (except `segments` holds the ORM dicts,
    which the router converts to `Segment` pydantic).

    Single transaction (no external writes possible between the three reads).
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

if (data == null) return <LoadingSpinner progress={0} status="載入中..." />;

if (data.status === 'queued' || data.status === 'processing') {
  return (
    <ProcessingLayout
      progress={data.progress}
      segments={data.segments}
      title={data.title}
    />
  );
}

if (data.status === 'failed') {
  return (
    <ProcessingLayout
      progress={data.progress}
      segments={data.segments}
      title={data.title}
      error={data.error_message ?? '處理失敗'}
    />
  );
}

// data.status === 'completed'
return <CompletedLayout data={data} />;
```

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
    const tick = async () => {
      try {
        const resp = await getSubtitles(videoId);  // 200 always, unless 404
        if (cancelled) return;
        setData(resp);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message);
      }
    };
    tick();  // immediate first fetch
    const id = setInterval(tick, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [videoId]);

  // Stop condition: once status is terminal, we COULD stop polling. But a
  // terminal status means subsequent polls return identical bytes at ~no cost
  // (SQLite cached read), so for implementation simplicity we keep polling
  // until the component unmounts. An explicit stop on `completed | failed`
  // is a micro-optimization we skip.

  return { data, error };
}
```

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

Six invariants, each one check-able against a test.

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
