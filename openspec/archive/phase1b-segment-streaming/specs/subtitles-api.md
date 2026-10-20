# Capability — Subtitles API (Phase 1b)

## Responsibilities
- Expose a single read endpoint, `GET /api/subtitles/{video_id}`, that returns the live state of a video's subtitle processing — regardless of whether it is queued, processing, completed, or failed.
- Report a unified response shape that carries `status`, `progress`, partial `segments`, optional `title` / `duration_sec`, and optional `error_code` / `error_message`.
- Preserve a completed-state response that is byte-compatible with the Phase 0 shape (additive fields only).
- Split the Phase 0 atomic `publish_video` write path into two atomic methods (`upsert_video_clear_segments` + `append_segments`) so that streaming writes can land chunk-by-chunk while preserving monotone reader guarantees.

## Public interfaces

### HTTP endpoint

```
GET /api/subtitles/{video_id}
```

```python
# backend/app/models/schemas.py

class SubtitleResponse(BaseModel):
    video_id: str
    status: Literal["queued", "processing", "completed", "failed"]
    progress: int                         # 0..100
    title: Optional[str] = None
    duration_sec: Optional[float] = None
    segments: list[Segment]
    error_code: Optional[str] = None
    error_message: Optional[str] = None
```

The existing `Segment` / `WordTiming` shapes from Phase 0 are unchanged.

### Repository surface

```python
# backend/app/repositories/videos_repo.py

class VideosRepo:
    def upsert_video_clear_segments(
        self, video_id: str, title: str, duration_sec: float, source: str,
    ) -> None: ...

    def append_segments(
        self, video_id: str, segments: list[dict],
    ) -> None: ...

    def get_video_view(self, video_id: str) -> Optional[dict]: ...
```

- `publish_video` is **deleted**. No backward-compat shim; all call sites migrate to the new pair.
- `get_video_view` is a single aggregate read. Returns `None` only if no job for this `video_id` was ever submitted.

## Behavior scenarios

### Endpoint: no job ever submitted

GIVEN no row in `jobs` with `video_id == V`
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 404` with body `{"error_code": "NOT_FOUND", ...}`.

### Endpoint: queued job, nothing processed yet

GIVEN the latest job for `video_id == V` is `queued`
AND no `videos` row or `segments` rows exist for V
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="queued"`, `progress=0`, `segments=[]`, `title=null`, `duration_sec=null`, `error_code=null`, `error_message=null`.

### Endpoint: processing, before the first chunk lands

GIVEN the latest job for V is `processing` with `progress` between 0 and 5
AND no `videos` row or `segments` rows exist yet
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="processing"`, `progress` equal to the job's progress, `segments=[]`, `title=null`, `duration_sec=null`.

### Endpoint: processing, some chunks already appended

GIVEN the latest job for V is `processing` with `progress=32`
AND the `videos` row for V exists with a known `title` and `duration_sec`
AND the `segments` table has rows for V with `idx` values `0..k` contiguous
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="processing"`, `progress=32`, `segments` containing all k+1 rows ordered by `idx`, `title` and `duration_sec` set.

### Endpoint: processing, videos row exists but no segments yet

GIVEN the latest job for V is `processing`
AND the `videos` row exists for V (probe completed)
AND the `segments` table is empty for V
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="processing"`, `segments=[]`, `title` and `duration_sec` from the `videos` row.

### Endpoint: completed, byte-compatible with Phase 0

GIVEN the latest job for V is `completed`
AND the `videos` row and all final `segments` exist
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="completed"`, `progress=100`, `segments` containing all rows ordered by `idx`, `title` and `duration_sec` set, `error_code=null`, `error_message=null`
AND a consumer that reads only the Phase 0 fields (`video_id`, `title`, `duration_sec`, `segments`) sees values identical to what Phase 0 would have returned for the same video.

### Endpoint: failed with partial segments

GIVEN the latest job for V is `failed`
AND the `videos` row exists
AND the `segments` table has some rows for V (from earlier successful chunks)
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="failed"`, `progress` equal to the job's last recorded progress, `segments` containing the partial rows ordered by `idx`, `error_code` and `error_message` set to the failure's canonical values.

### Endpoint: failed with no segments

GIVEN the latest job for V is `failed`
AND no `segments` rows exist for V
WHEN the client calls `GET /api/subtitles/V`
THEN the response is `HTTP 200` with `status="failed"`, `segments=[]`, `title` and `duration_sec` present only if the `videos` row exists, `error_code` and `error_message` set.

### Endpoint: resubmission for the same video_id

GIVEN V has previously been processed (there is a historic `completed` job)
AND a new job is later submitted and is now `processing`
WHEN the client calls `GET /api/subtitles/V`
THEN the response reflects the **latest** job (ordered by `created_at DESC LIMIT 1`) — `status="processing"`, and `segments` reflect whatever has been appended under the fresh run (see `upsert_video_clear_segments` scenario below).

### Repository: upsert_video_clear_segments is atomic

GIVEN any prior state for `video_id == V`
WHEN `upsert_video_clear_segments(V, title, duration_sec, source)` executes
THEN within a single SQLite transaction: the `videos` row for V is upserted; all rows in `segments` for V are deleted
AND a reader that polls during the method never observes a partially-updated state (either the pre-call state or the post-call state, never a mix).

### Repository: append_segments is atomic per chunk

GIVEN `upsert_video_clear_segments(V, ...)` has already been called
AND previously-appended segments exist with `idx` values `0..k`
WHEN `append_segments(V, [segment_{k+1}, ..., segment_{k+m}])` executes
THEN within a single SQLite transaction, all m new rows are inserted
AND if any insert in the batch fails, the entire batch rolls back (no partial-chunk visibility).

### Repository: append_segments rejects idx collision

GIVEN `segments` rows for V already exist with `idx == k`
WHEN `append_segments(V, [segment_with_idx_k])` is called
THEN the repository raises (enforced by the `(video_id, idx)` primary key); the caller is responsible for assigning monotone idx values.

### Repository: get_video_view returns None when no job exists

GIVEN there is no `jobs` row for V at any time
WHEN `get_video_view(V)` is called
THEN it returns `None`.

### Repository: get_video_view reads are internally consistent

GIVEN a row exists in `jobs`, `videos`, and `segments` for V
WHEN `get_video_view(V)` is called
THEN the method MUST execute `BEGIN DEFERRED` before the SELECTs and `COMMIT` after, so the three reads are observed under a single snapshot
AND on any exception during the reads, the method executes `ROLLBACK` before re-raising.

### Repository: get_video_view transaction shape is observable

GIVEN a test that spies on `conn.execute`
WHEN `get_video_view(V)` runs
THEN the observed call sequence contains `BEGIN DEFERRED` → three SELECTs → `COMMIT` in order; no intermediate COMMIT appears.

### Repository: get_video_view returns latest job

GIVEN multiple `jobs` rows exist for V (for example, a historic `completed` job and a later `processing` job)
WHEN `get_video_view(V)` is called
THEN the returned `status` and `progress` come from the row with the greatest `created_at`.

### Segment idx invariant

GIVEN a successful completed run
WHEN a client reads `/subtitles/V`
THEN `segments` is ordered by `idx`, `idx` values are contiguous starting from 0, and no duplicates exist.

## Invariants

1. **Reader monotonicity.** At any time t, the segments returned by `GET /subtitles/{video_id}` are a prefix of the segments returned at any time t' > t for the same video — *unless* an intervening resubmission invokes `upsert_video_clear_segments`, after which the prefix invariant resets.
2. **Additive Phase 0 compatibility.** A consumer that inspects only `video_id`, `title`, `duration_sec`, and `segments` on a `completed` response sees Phase 0–equivalent bytes.
3. **404 is reserved for "never submitted".** Any state where a job row for `video_id` exists returns `HTTP 200`, including `failed` with zero segments.
4. **Latest job wins.** `status`, `progress`, `error_code`, `error_message` always come from the newest job by `created_at`.
5. **Atomic per-chunk writes.** `append_segments` is one transaction per chunk; no cross-chunk atomicity is promised.
6. **FK integrity preserved.** `segments.video_id` still has `REFERENCES videos(video_id) ON DELETE CASCADE`.
7. **No endpoint removal.** `GET /api/subtitles/jobs/{job_id}` remains available for debugging; the frontend does not consume it after Phase 1b.
8. **`get_video_view` uses an explicit transaction.** `BEGIN DEFERRED` / `COMMIT` wrap the three SELECTs so that WAL-mode concurrency cannot tear the view across `jobs`, `videos`, `segments`.
9. **`error_message` is sanitized before reaching the API.** Responses with `status="failed"` carry a value from `_SAFE_MESSAGES[error_code]` only; raw exception text never reaches the response body.

## Non-goals (Phase 1b)

- Removing `GET /api/subtitles/jobs/{job_id}`.
- Adding a `current_stage` string to `JobStatus` or `SubtitleResponse`.
- SSE / WebSocket transport.
- Auth or rate limiting on `/subtitles/{video_id}` (CORS-pinned localhost continues).
- Supplying a Phase 0 → Phase 1b response-shape shim; the bump is direct.
- Changing the `segments` table schema.
