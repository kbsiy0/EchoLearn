# Capability — Data Layer

## Responsibilities
- Own the on-disk persistence format (SQLite) for jobs, videos, and segments.
- Provide a connection factory that applies WAL mode and foreign-key enforcement.
- Expose repository functions that are the only legitimate way for the rest of the app to read/write persistent state.
- Survive process restart without data loss and without leaving in-flight jobs stuck.

## Public interfaces

### Schema (`backend/app/db/schema.sql`)
Three tables — `jobs`, `videos`, `segments` — per `design.md` Section 2. Schema file is idempotent (`CREATE TABLE IF NOT EXISTS …`) and applied on first `get_connection()` call.

### Connection factory
```python
# backend/app/db/connection.py
def get_connection() -> sqlite3.Connection: ...
#   applies PRAGMA journal_mode=WAL, PRAGMA foreign_keys=ON
```

### Jobs repository
```python
# backend/app/repositories/jobs_repo.py
def create(job_id: str, video_id: str) -> None: ...
def update_progress(job_id: str, progress: int) -> None: ...
def update_status(
    job_id: str,
    status: Literal['queued','processing','completed','failed'],
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None: ...
def get(job_id: str) -> Optional[JobStatus]: ...
def find_active_for_video(video_id: str) -> Optional[JobStatus]: ...
#   returns the most recent job for the video whose status is queued or processing
def sweep_stuck_processing(older_than_sec: float) -> int: ...
#   marks long-running processing rows as failed with INTERNAL_ERROR; returns count swept
#   older_than_sec is a parameter (not a hard-coded 60) so tests can use small thresholds
```

### Videos repository
```python
# backend/app/repositories/videos_repo.py
def publish_video(
    video_id: str,
    title: str,
    duration_sec: float,
    source: str,
    segments: list[Segment],
) -> None: ...
#   ATOMIC: upsert of the videos row + insert of all segments rows, in a single SQLite transaction.
#   This is the ONLY sanctioned way for the pipeline to make a video observable.

def get_video(video_id: str) -> Optional[VideoSummary]: ...
def list_videos() -> list[VideoSummary]: ...
#   ordered by created_at DESC
def get_segments(video_id: str) -> list[Segment]: ...
#   ordered by idx ASC
```

## Invariants
- **WAL mode always.** `get_connection()` is the only code path that opens a connection; both routers and the pipeline go through it.
- **Progress monotonic + surfacing.** `update_progress` never lowers progress. In test mode (fixture flag `EL_TEST_STRICT=1`), a lowering attempt raises `AssertionError` so bugs surface loudly. In production it logs a WARN and becomes a no-op. T02 acceptance verifies both paths.
- **Atomic publish (Option A).** `publish_video` is a single SQLite transaction that either writes the `videos` row and all `segments` rows, or writes neither. No partial state is observable at any intermediate point. Routers and pipeline MUST NOT bypass `publish_video` to write `videos` or `segments` independently.
- **Reprocess cleanly.** `publish_video` replaces any existing segments for the `video_id` as part of its transaction (explicit `DELETE FROM segments WHERE video_id = ?` followed by inserts, all inside the same transaction).
- **No foreign data format.** JSON cache files are not read or written by any repository method. The only persistent store is the DB.
- **`video_id` safety.** Every write method validates `video_id` against `^[A-Za-z0-9_-]{11}$` before issuing SQL. Malformed IDs raise at the repo layer; they never reach SQL. Tested in T03.

## Non-goals
- Full-text search across subtitles (Phase 1+).
- Per-word querying via SQL — words stay inside `words_json`.
- Multi-user isolation, per-user progress tracking (Phase 1+).
- Migrations framework — Phase 0 schema is authoritative; breaking schema changes will require a fresh DB.
