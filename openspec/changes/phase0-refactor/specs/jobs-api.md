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
| POST   | `/api/subtitles/jobs`             | `{ "url": string }`         | `JobStatus`              |
| GET    | `/api/subtitles/jobs/{job_id}`    | —                           | `JobStatus` (404 if unknown) |
| GET    | `/api/subtitles/{video_id}`       | —                           | `SubtitleResponse` (404 if not completed) |
| GET    | `/api/videos`                     | —                           | `list[VideoSummary]` ordered by `created_at DESC` |

### Response shapes

```python
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
def submit(job_id: str) -> None: ...
def shutdown() -> None: ...
#   wraps a module-level ThreadPoolExecutor(max_workers=2)
```

## Invariants
- **Idempotent submission for in-flight work.** A `POST` for a `video_id` with an existing `queued` or `processing` job returns that job instead of creating a new one.
- **Cache-hit short-circuit.** A `POST` for a `video_id` that already has a `videos` row returns a synthetic `completed` job; no new pipeline run is started.
- **Retry after failure creates a new job.** A `POST` for a `video_id` whose most recent job is `failed` creates a fresh `queued` job.
- **Monotonic progress in responses.** `GET /api/subtitles/jobs/{id}` never returns a lower progress than a previous call for the same job.
- **404 contracts.** Unknown `job_id` and not-yet-completed `video_id` both return HTTP 404.
- **Restart recovery.** On startup, any `processing` rows older than 60 seconds are swept to `failed` with `INTERNAL_ERROR`.
- **Executor bounded.** Concurrent worker threads are capped at 2 (`ThreadPoolExecutor(max_workers=2)`).

## Error contract
Failures are reported inside `JobStatus.status='failed'` with `error_code` drawn from the taxonomy in `design.md` Section 4. The HTTP status for a failed job is still 200; clients discover failure via the body, not the HTTP code.

## Non-goals
- WebSocket / SSE streaming of progress (client polls).
- Auth, per-user job isolation (Phase 1+).
- Retrying failed jobs automatically (client decides to resubmit).
- Cancellation of in-flight jobs (Phase 1).
