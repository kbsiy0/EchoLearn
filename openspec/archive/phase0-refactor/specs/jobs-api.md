# Capability — Jobs API

## Responsibilities
- Accept subtitle generation requests and return a trackable `job_id`.
- Expose job status polling with monotonic progress.
- Return finished subtitles for a completed video.
- List processed videos for the HomePage history.
- Survive process restart without losing submitted-but-unfinished jobs (they fail cleanly rather than appearing to still be processing).

## Public interfaces

### HTTP endpoints

| Method | Path                              | Request                     | Response                 |
|--------|-----------------------------------|-----------------------------|--------------------------|
| POST   | `/api/subtitles/jobs`             | `{ "url": string }` (max 2048 chars) | `JobStatus` on success; `{error_code, error_message}` (HTTP 400) on `INVALID_URL` |
| GET    | `/api/subtitles/jobs/{job_id}`    | —                           | `JobStatus` (404 if unknown) |
| GET    | `/api/subtitles/{video_id}`       | —                           | `SubtitleResponse` (404 if not completed) |
| GET    | `/api/videos`                     | —                           | `list[VideoSummary]` ordered by `created_at DESC` |

### Response shapes

```python
class CreateJobRequest(BaseModel):
    url: constr(max_length=2048)

class JobStatus(BaseModel):
    job_id: str
    video_id: str
    status: Literal['queued','processing','completed','failed']
    progress: int                  # 0..100
    error_code: Optional[str]
    error_message: Optional[str]

class WordTiming(BaseModel):
    text: str
    start: float
    end: float

class Segment(BaseModel):
    idx: int
    start: float
    end: float
    text_en: str
    text_zh: str
    words: list[WordTiming]

class SubtitleResponse(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    segments: list[Segment]

class VideoSummary(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    created_at: str
```

### Runner
```python
# backend/app/jobs/runner.py
class JobRunner:
    def __init__(
        self,
        *,
        max_workers: int = 2,
        stale_threshold_sec: float = 60.0,
    ): ...
    def submit(self, job_id: str) -> None: ...
    def startup_sweep(self) -> int: ...
    def shutdown(self) -> None: ...
```

- `max_workers` and `stale_threshold_sec` are constructor arguments, enabling tests to use a short threshold (e.g., `0.1s`).
- Production default is 60 seconds; test default (injected via fixture) is typically `0.1s`.
- `startup_sweep()` is called from the FastAPI lifespan `startup` hook.

## Invariants
- **Idempotent submission for in-flight work.** A `POST` for a `video_id` with an existing `queued` or `processing` job returns that job instead of creating a new one.
- **Cache-hit short-circuit.** A `POST` for a `video_id` that already has a `videos` row returns a synthetic `completed` job; no new pipeline run is started.
- **Retry after failure creates a new job.** A `POST` for a `video_id` whose most recent job is `failed` creates a fresh `queued` job.
- **Monotonic progress in responses.** `GET /api/subtitles/jobs/{id}` never returns a lower progress than a previous call for the same job.
- **404 contracts.** Unknown `job_id` and not-yet-completed `video_id` both return HTTP 404.
- **400 on INVALID_URL.** Malformed URL or `video_id` failing regex returns HTTP 400 with body `{error_code: 'INVALID_URL', error_message: <safe string>}`. `error_message` MUST NOT contain stack traces, parser internals, or raw exception text.
- **Restart recovery.** On startup, any `processing` rows older than `stale_threshold_sec` are swept to `failed` with `INTERNAL_ERROR: server restarted during processing`. Job records are NEVER left as perpetually `processing`.
- **Executor bounded.** Concurrent worker threads are capped at `max_workers` (default 2).
- **CORS preserved.** Router split does not remove or loosen the existing CORS middleware (`allow_origins=['http://localhost:5173']`). `OPTIONS /api/videos` returns expected CORS headers.

## Error contract
Failures other than `INVALID_URL` are reported inside `JobStatus.status='failed'` with `error_code` drawn from the taxonomy in `design.md` Section 4. The HTTP status for a failed job (other than intake-time `INVALID_URL`) is 200; clients discover failure via the body, not the HTTP code.

## Frontend consumer — `useJobPolling`

```typescript
// frontend/src/features/jobs/hooks/useJobPolling.ts
function useJobPolling(jobId: string | null): {
  job: JobStatus | null;
  error: Error | null;
};
```

Behavioral contract:
- **Interval.** Polls `GET /api/subtitles/jobs/{jobId}` on a fixed 1000ms interval (no exponential backoff in Phase 0).
- **Terminal-state stop.** Stops polling as soon as `status` is `completed` or `failed`; final `JobStatus` remains in state.
- **Cancel on unmount.** Clears the pending interval and aborts any in-flight fetch on unmount.
- **Null jobId.** Returns `{job: null, error: null}` and performs no polling.
- **Network error.** Surfaces via `error` but does not stop polling (transient 5xx tolerated); does not retry faster than the interval.

This hook is being **created** in T06 (extracted from `App.tsx`'s inline polling logic), not merely relocated.

## Non-goals
- WebSocket / SSE streaming of progress (client polls).
- Auth / rate-limiting. Phase 0 relies on CORS localhost binding. Deployers MUST add auth before exposing the API beyond localhost.
- Retrying failed jobs automatically (client decides to resubmit).
- Cancellation of in-flight jobs (Phase 1).
