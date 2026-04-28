# Phase 2: Video History and Learning Progress Recovery — Design

Readers should be able to implement from this document alone. The six decisions
locked in `proposal.md` are LOCKED — this design expands them, it does not
relitigate them.

---

## Section 1 — Overview

Phase 2 turns the HomePage from a chronological "recent uploads" list into a
**resumption-oriented learning surface**, and turns the player from "always
plays from t=0 with default speed" into a **stateful resume target** that
remembers per-video position, segment index, playback rate, and loop state.

The two coupled features share a single new data table (`video_progress`) and a
single new HTTP resource (`/api/videos/{video_id}/progress` with GET / PUT /
DELETE). Everything else is plumbing: a frontend hook to bridge the resource
to the player, a card component to render history rows, and a list-endpoint
modification that LEFT JOINs progress so the existing `GET /api/videos`
response continues to serve the HomePage with one round trip.

Progress is written event-driven (pause / seek / rate-change / loop-change /
visibility-hidden / unmount) with 1-second debounce. Reads happen exactly once
per `/watch/:videoId` mount, gated behind `useSubtitleStream`'s first-poll
completion and `useYouTubePlayer.isReady`. Failure of any progress operation
NEVER blocks the player — progress is best-effort enrichment.

---

## Section 2 — Data model

### Table

```sql
-- backend/app/db/schema.sql (APPENDED)

CREATE TABLE IF NOT EXISTS video_progress (
  video_id          TEXT PRIMARY KEY,
  last_played_sec   REAL NOT NULL,
  last_segment_idx  INTEGER NOT NULL,
  playback_rate     REAL NOT NULL,
  loop_enabled      INTEGER NOT NULL,        -- 0 or 1
  updated_at        TEXT NOT NULL,           -- ISO-8601 UTC; doubles as last_played_at for sort
  FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_progress_updated_at
  ON video_progress(updated_at DESC);
```

**Why `video_id` as PRIMARY KEY** (not a synthetic `progress_id`):
- One row per video; resumption is per-video, not per-session.
- `INSERT … ON CONFLICT(video_id) DO UPDATE` collapses first-time + update into
  one upsert, matching the API's last-write-wins PUT semantics.
- The PRIMARY KEY index serves the GET-by-video_id read; no extra index needed.

**Why `ON DELETE CASCADE`**:
- Defensively guarantees no orphan progress rows. Phase 2 does not delete
  `videos` rows from any code path (hard-delete is explicitly out of scope per
  proposal §"Out of scope"), so this CASCADE is dormant. It fires only if a
  future phase introduces a hard-delete operation, at which point we want
  progress to disappear with the video.
- The CASCADE is asserted by schema, not by API behavior: `subtitles-api` and
  `progress-api` callers never observe the cascade because they never delete
  videos rows.

**Why `loop_enabled INTEGER NOT NULL`** (0/1) instead of a SQLite `BOOLEAN`:
- SQLite has no real boolean type; storing as INTEGER and converting at the
  repo boundary (`bool(row["loop_enabled"])`) keeps the DDL portable and the
  Python type clean.
- `NOT NULL` because the schema's contract is "always have a stored value once
  the row exists"; nullability would fork validation logic.

**Why `idx_progress_updated_at` DESC**:
- The HomePage's modified `list_videos()` uses progress's `updated_at` as part
  of the ORDER BY (Section 12). The DESC index allows the JOIN-and-sort plan
  to read progress rows in descending order without a separate sort pass.
- Negligible space cost (one row per watched video; expected N < 100 in
  personal use).

### Pydantic models

```python
# backend/app/models/schemas.py (ADDITIONS)

class VideoProgress(BaseModel):
    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: bool
    updated_at: str    # ISO-8601 UTC, server-stamped on every PUT

class VideoProgressIn(BaseModel):
    """PUT body — `updated_at` is server-stamped and not accepted from clients."""
    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: bool

class VideoSummary(BaseModel):
    video_id: str
    title: str
    duration_sec: float
    created_at: str
    progress: VideoProgress | None = None    # NEW — null when never played
```

**Backward compatibility note for `VideoSummary`**: making `progress` an
optional `Field(default=None)` keeps every existing test fixture and consumer
working unchanged. Phase 0/1b consumers that read only the original four
fields continue to see the same JSON bytes for those fields. This honors the
proposal's "Open question 1" recommendation: stay backward-compatible without
versioning.

### Row → model mapping

| DB column            | Python type | Pydantic field      | Conversion at repo boundary |
|----------------------|-------------|---------------------|-----------------------------|
| `last_played_sec`    | REAL        | `float`             | direct                      |
| `last_segment_idx`   | INTEGER     | `int`               | direct                      |
| `playback_rate`      | REAL        | `float`             | direct                      |
| `loop_enabled`       | INTEGER     | `bool`              | `bool(row["loop_enabled"])` |
| `updated_at`         | TEXT        | `str` (ISO-8601)    | direct                      |

---

## Section 3 — Backend layout

```
backend/app/
  db/
    schema.sql                    (MODIFIED — append video_progress + index)
  repositories/
    progress_repo.py              (NEW — get / upsert / delete)
    videos_repo.py                (MODIFIED — list_videos LEFT JOINs progress + custom ORDER BY)
  routers/
    progress.py                   (NEW — GET / PUT / DELETE /api/videos/{video_id}/progress)
    videos.py                     (MODIFIED — emit VideoSummary with progress field)
  models/
    schemas.py                    (MODIFIED — add VideoProgress, VideoProgressIn; extend VideoSummary)
  main.py                         (MODIFIED — register progress router)

backend/tests/
  unit/
    test_repositories_progress.py (NEW)
    test_schemas.py               (EXTENDED — VideoProgress, VideoSummary.progress)
  integration/
    test_progress_router.py       (NEW)
    test_videos_list.py           (EXTENDED — progress JOIN + ORDER BY cases)
    test_lifespan_boot.py         (EXTENDED — schema migration smoke)
```

### Per-file responsibility statements

| File | Responsibility |
|---|---|
| `db/schema.sql` | Single source of truth for the `video_progress` table DDL and its index. Idempotent (`IF NOT EXISTS`). Loaded once per DB path on first connection per existing `db/connection.py` cache. |
| `repositories/progress_repo.py` | All SQL touching the `video_progress` table. Owns row→model conversion (INTEGER ↔ bool, server-stamping `updated_at`). Validates `video_id` via shared `validate_video_id`, validates value ranges per Section 5. |
| `repositories/videos_repo.py` | UNCHANGED methods stay; `list_videos()` is the only modified method. New SQL: `SELECT … FROM videos LEFT JOIN video_progress USING (video_id) ORDER BY (progress.updated_at IS NULL), progress.updated_at DESC, videos.created_at DESC`. Returns rows that downstream code converts to `VideoSummary` with optional `progress`. |
| `routers/progress.py` | Three thin handlers calling `ProgressRepo`. GET 200/404, PUT 204, DELETE 204. Validation errors → 400 with `error_code=ErrorCode.VALIDATION_ERROR` (via router-local `RequestValidationError` handler — see §4). PUT references a non-existent videos row: attempt `repo.upsert(...)` directly, catch `sqlite3.IntegrityError` (FK violation), re-raise as `HTTPException(404, {error_code: ErrorCode.NOT_FOUND, error_message: "video not found"})`. **No SELECT-then-UPSERT pre-check** — the catch is race-free and simpler. Errors flatten through the existing `http_exception_handler` in `main.py`. |
| `routers/videos.py` | Modified to read the LEFT-JOINed list and shape into `VideoSummary` (with nested `VideoProgress` when present). |
| `models/schemas.py` | Adds `VideoProgress` (full) and `VideoProgressIn` (PUT body). Extends `VideoSummary` with optional `progress` field. |
| `main.py` | One-line `app.include_router(progress_router.router)` addition. |

---

## Section 4 — Backend API contract

### Endpoint table

| Method | Path | Status | Body | Notes |
|---|---|---|---|---|
| GET | `/api/videos/{video_id}/progress` | 200 | `VideoProgress` | row exists; `last_played_sec` clamped to `videos.duration_sec` if greater |
| GET | `/api/videos/{video_id}/progress` | 404 | `{ "error_code": "NOT_FOUND", "error_message": "progress not found" }` | no row for this video |
| GET / DELETE | `/api/videos/{video_id}/progress` | 404 | `{ "error_code": "NOT_FOUND", "error_message": "invalid video_id" }` | `video_id` fails 11-char regex (matches `routers/subtitles.py:25` precedent) |
| PUT | `/api/videos/{video_id}/progress` | 204 | empty | first-time create OR update; server stamps `updated_at` |
| PUT | `/api/videos/{video_id}/progress` | 400 | `{ "error_code": "VALIDATION_ERROR", "error_message": "<reason>" }` | range/sign violations per Section 5 (raised as `ValueError` in repo, mapped to `HTTPException(400, ...)` in router) |
| PUT | `/api/videos/{video_id}/progress` | 400 | `{ "error_code": "VALIDATION_ERROR", "error_message": "<pydantic first-error>" }` | extra field, wrong type, missing field — handled by router-local `RequestValidationError` handler; see "Validation handler" row below |
| PUT | `/api/videos/{video_id}/progress` | 404 | `{ "error_code": "NOT_FOUND", "error_message": "video not found" }` | `repo.upsert(...)` raises `sqlite3.IntegrityError` (FK violation); router catches and re-raises as 404. Race-free per §5. |
| DELETE | `/api/videos/{video_id}/progress` | 204 | empty | idempotent; succeeds whether row existed or not |
| GET | `/api/videos` | 200 | `VideoSummary[]` | each summary has `progress: VideoProgress \| null`; sorted per Section 12 |

**Validation handler (router-local).** `routers/progress.py` registers a
`@router.exception_handler(RequestValidationError)` that converts Pydantic
v2's default 422 + `{detail: [...]}` shape into the canonical envelope:

```python
@router.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    first_error = exc.errors()[0]
    msg = first_error.get("msg", "validation error")
    raise HTTPException(
        status_code=400,
        detail={
            "error_code": ErrorCode.VALIDATION_ERROR,
            "error_message": msg,
        },
    )
```

This mirrors the pattern in `routers/subtitles.py:25` and
`routers/jobs.py:83`. Clients NEVER observe a 422 from
`/api/videos/{id}/progress`. The `app/main.py` `http_exception_handler`
then flattens `detail=dict` into the canonical response envelope.

**Why no PUT-time `updated_at` from the client**: the server is the timekeeper.
Accepting client timestamps would expose the sort order to clock skew or
malicious clients. The PUT body uses `VideoProgressIn` (no `updated_at`); the
server stamps `now_iso()` at insert/update time. The response (GET) carries
the server-stamped value.

**Why 404 distinguishes "video not found" from "progress not found"**:
- `GET /progress` 404 is the expected path for "user has never played this
  video" — a normal first-mount state. The frontend treats it as `null` data.
- `PUT /progress` 404 (video not found) signals a real bug: the frontend has a
  `video_id` that does not correspond to any uploaded video. The frontend
  surfaces nothing visible (silent log per proposal's error-handling
  philosophy), but the test suite asserts the distinction.

### `error_code` shapes

The backend uses the existing `ErrorCode` enum in `services/errors.py`. Phase
2 adds one new code:

```python
# services/errors.py (ADDITION)
class ErrorCode(str, Enum):
    # … existing codes …
    VALIDATION_ERROR = "VALIDATION_ERROR"
```

`SAFE_MESSAGES` does NOT add an entry for `VALIDATION_ERROR` because validation
errors carry a specific, safe-to-expose reason string (e.g., `"playback_rate
must be in [0.5, 2.0]"`). The router constructs this string per-violation.

**Always reference the enum member, never the bare string.** Router and
test code use `ErrorCode.VALIDATION_ERROR` and `ErrorCode.NOT_FOUND`,
which JSON-serialize to `"VALIDATION_ERROR"` / `"NOT_FOUND"` because
`ErrorCode` is a `str`-Enum. Inline string literals (`"VALIDATION_ERROR"`)
are a code-review nit.

### `list_videos` LEFT JOIN

```sql
SELECT
  v.video_id, v.title, v.duration_sec, v.created_at,
  p.last_played_sec, p.last_segment_idx,
  p.playback_rate, p.loop_enabled, p.updated_at AS progress_updated_at
FROM videos v
LEFT JOIN video_progress p ON p.video_id = v.video_id
ORDER BY
  (p.updated_at IS NULL) ASC,    -- FALSE (with-progress) first
  p.updated_at DESC,             -- newest progress first
  v.created_at DESC;             -- tiebreaker for never-played videos
```

**Why three-clause ORDER BY**:
- Clause 1 (`p.updated_at IS NULL`) puts videos *with* progress before videos
  without. SQLite evaluates `IS NULL` to 0 (false) or 1 (true); ASC means
  false first.
- Clause 2 sorts the with-progress group by progress recency (newest first).
- Clause 3 sorts the without-progress group by creation (newest first).

This is one query, one sort. The DESC index on `video_progress.updated_at`
serves clause 2 efficiently.

---

## Section 5 — Backend repos & sanitization invariants

### `ProgressRepo` interface

```python
# backend/app/repositories/progress_repo.py

class ProgressRepo:
    def __init__(self, conn: sqlite3.Connection) -> None: ...

    def get(self, video_id: str) -> Optional[dict]:
        """Return the progress row as a dict (with bool conversion) or None.

        Clamps last_played_sec to videos.duration_sec if greater (defensive
        against re-transcribe shrinkage). The clamp is read-side only; the
        stored row is unchanged.
        """

    def upsert(
        self,
        video_id: str,
        *,
        last_played_sec: float,
        last_segment_idx: int,
        playback_rate: float,
        loop_enabled: bool,
    ) -> None:
        """Insert-or-update with server-stamped `updated_at`.

        Validates inputs per the rules below; raises ValueError on violation.
        Server stamps `now_iso()` at execution time.
        """

    def delete(self, video_id: str) -> None:
        """Idempotent delete; never raises if no row exists."""
```

### Validation rules (raised as `ValueError` from the repo, mapped to 400 by the router)

| Field | Rule | Reason string |
|---|---|---|
| `last_played_sec` | `>= 0` | `"last_played_sec must be >= 0"` |
| `last_segment_idx` | `>= 0` | `"last_segment_idx must be >= 0"` |
| `playback_rate` | `0.5 <= rate <= 2.0` | `"playback_rate must be in [0.5, 2.0]"` |
| `loop_enabled` | `isinstance(bool)` | enforced by Pydantic; rejected at parse time |

**Why repo-layer validation, not router-layer**: the repo is the boundary
between "validated input" and "DB row". Validation lives next to the SQL it
guards. The router's job is HTTP shape, not business rules.

**No clamping on PUT**: PUT writes the value as-is. Clamping happens only on
GET (so a stored value that is later "too large" because the video was
re-transcribed shorter still produces a valid resume target). PUT-side
clamping would silently rewrite client intent — confusing.

### FK existence check via IntegrityError catch (race-free)

`ProgressRepo.upsert()` does **not** pre-check that the videos row exists.
Instead, the upsert SQL fires; if no `videos` row exists for the supplied
`video_id`, SQLite's foreign-key enforcement raises
`sqlite3.IntegrityError` from inside the INSERT statement. The router
catches this exception and maps it to HTTP 404 with `error_code =
ErrorCode.NOT_FOUND` and `error_message = "video not found"`.

This is **race-free** without a `BEGIN DEFERRED` transaction: the FK check
is part of the INSERT statement itself, so a videos row deleted between a
hypothetical pre-check and the upsert cannot leak. The pattern eliminates
the SELECT-then-UPSERT TOCTOU window entirely.

```python
# Repo
def upsert(self, video_id: str, *, last_played_sec, ...) -> None:
    validate_video_id(video_id)
    _validate_progress_inputs(...)
    self.conn.execute(
        "INSERT INTO video_progress (...) VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(video_id) DO UPDATE SET ...",
        (...),
    )
    # may raise sqlite3.IntegrityError if videos.video_id missing — bubbles up

# Router
try:
    ProgressRepo(conn).upsert(video_id, **body.model_dump())
except sqlite3.IntegrityError:
    raise HTTPException(
        status_code=404,
        detail={
            "error_code": ErrorCode.NOT_FOUND,
            "error_message": "video not found",
        },
    )
```

`ProgressRepo.upsert` does NOT silently swallow `IntegrityError`; the
exception propagates to the router for HTTP shaping.

### `videos_repo.list_videos()` modification

The method's **return type changes** from `list[sqlite3.Row]` to
`list[dict]`, where each dict carries the LEFT-JOINed columns. This is an
intentional internal-boundary break: there is one caller (`routers/videos.py`)
and migrating it is part of T05.

```python
def list_videos(self) -> list[dict]:
    """Return one row per video, each enriched with progress when present.

    Sorted with-progress first (by progress.updated_at DESC), then
    without-progress (by videos.created_at DESC). See Section 4 for the SQL.
    """
```

### Server-stamped `updated_at` monotonicity

The PUT path computes `now_iso()` immediately before the INSERT/UPDATE. Two
PUTs from the same client back-to-back produce two ISO timestamps that
**may** be equal at microsecond granularity if the system clock has lower
resolution; the second PUT still wins by virtue of UPSERT semantics
(`ON CONFLICT … DO UPDATE` overwrites the row). The sort uses `>=` semantics
so equal timestamps are stable but unordered between themselves — acceptable
since they are the same row anyway.

---

## Section 6 — Frontend layout

```
frontend/src/
  api/
    progress.ts                                  (NEW — getProgress/putProgress/deleteProgress)
  features/
    player/
      hooks/
        useVideoProgress.ts                      (NEW)
      components/
        ResumeToast.tsx                          (NEW)
        CompletedLayout.tsx                      (MODIFIED — wires hook + resume effect + toast)
    jobs/
      components/
        VideoCard.tsx                            (NEW)
  routes/
    HomePage.tsx                                 (MODIFIED — replace inline <li> with <VideoCard>)
  types/
    subtitle.ts                                  (MODIFIED — extend VideoSummary, add VideoProgress)

frontend/src/__tests__/ (or co-located *.test.ts)
  api/progress.test.ts                           (NEW)
  features/player/hooks/useVideoProgress.test.ts (NEW)
  features/player/components/ResumeToast.test.tsx (NEW)
  features/jobs/components/VideoCard.test.tsx    (NEW)
  routes/HomePage.test.tsx                       (EXTENDED — sort + reset flow)
```

### Per-file responsibility statements

| File | Responsibility |
|---|---|
| `api/progress.ts` | Three thin functions: `getProgress(videoId): Promise<VideoProgress \| null>` (404 → null, other errors throw); `putProgress(videoId, body)`; `deleteProgress(videoId)`. Uses shared `API_BASE` from `api/base.ts`. |
| `features/player/hooks/useVideoProgress.ts` | Owns the lifecycle of one video's progress. Loads on mount, exposes `value: VideoProgress \| null` and `loaded: boolean`, exposes `save(partial)` (debounced PUT) and `reset()` (immediate DELETE). Handles flush on tab close + unmount. |
| `features/player/components/ResumeToast.tsx` | Stateless presenter. Props: `playedAtSec`, `segmentIdx`, `onDismiss`, `onRestart`. Auto-dismisses after 5s wall-clock via internal `setTimeout`. |
| `features/player/components/CompletedLayout.tsx` | Modified: composes `useVideoProgress`, runs the resume effect (Section 8), renders `ResumeToast` once after restoration, propagates save events from existing pause/seek/rate/loop callbacks (Section 9). |
| `features/jobs/components/VideoCard.tsx` | Stateless card. Props: `summary: VideoSummary`, `onClick`, `onReset`. Renders title, duration, progress bar (when `summary.progress`), and "重置進度" button (only when progress exists). Click vs reset isolation via `e.stopPropagation()`. |
| `routes/HomePage.tsx` | Modified: maps `videos` to `<VideoCard>` instances, defines `handleReset(videoId)` which calls `deleteProgress` then refetches the list. Surfaces inline reset error per card. |
| `types/subtitle.ts` | Adds `VideoProgress` interface, extends `VideoSummary` with `progress: VideoProgress \| null`. |

---

## Section 7 — Frontend hook contract: `useVideoProgress`

### Signature

```ts
// frontend/src/features/player/hooks/useVideoProgress.ts

export interface VideoProgress {
  last_played_sec: number;
  last_segment_idx: number;
  playback_rate: number;
  loop_enabled: boolean;
  updated_at: string;
}

export interface UseVideoProgressResult {
  value: VideoProgress | null;     // current cached progress (null = never-played or 404)
  loaded: boolean;                  // true after first GET resolves (success or 404)
  save: (partial: Partial<Omit<VideoProgress, 'updated_at'>>) => void;
  reset: () => Promise<void>;       // immediate DELETE; resolves on success, rejects on error
}

export function useVideoProgress(videoId: string | null): UseVideoProgressResult;
```

### Internal state machine

```
┌─────────────────┐  videoId set        ┌──────────────────┐ GET 200
│  loaded=false   │ ──────────────────→ │  loading         │ ─────────→  loaded=true, value=resp
│  value=null     │                     │  GET in flight   │
└─────────────────┘                     └──────────────────┘ GET 404
                                                  │         ─────────→  loaded=true, value=null
                                                  │
                                                  ▼ GET 5xx / network
                                            loaded=true, value=null
                                            (silent — best-effort)
```

After `loaded=true`, the hook holds:
- `value`: the most recent value returned by GET (or set by `save()`).
- A debounce-pending state (private): the partial diff and a `setTimeout` handle.
- A "current full state" cache (private): the merged `value + pending diff`,
  used for flushing.

### `save(partial)` semantics

Each call merges `partial` into the cached current state and resets a 1-second
debounce timer. The next time the timer fires (or a flush trigger fires), the
hook PUTs the merged state.

```
save({last_played_sec: 120}) at t=0     → debounce pending, fire at t=1.0
save({playback_rate: 1.5})    at t=0.4  → debounce reset,  fire at t=1.4
save({loop_enabled: true})    at t=0.9  → debounce reset,  fire at t=1.9
                                          → at t=1.9, PUT {last_played_sec: 120,
                                                            last_segment_idx: <last cached>,
                                                            playback_rate: 1.5,
                                                            loop_enabled: true}
```

The merge guarantees that no field is "stale": a call that updates only
`playback_rate` keeps the previous `last_played_sec`. The PUT always sends a
complete `VideoProgressIn`.

**Coalesce invariant**: N `save()` calls within a 1-second window produce
exactly one PUT.

### Flush triggers (force-immediate PUT, no debounce wait)

| Trigger | When | Why |
|---|---|---|
| `visibilitychange` to hidden | tab backgrounded | mobile browsers may discard background timers; flush before they do |
| `beforeunload` | browser closing or navigating away | last chance to persist before page is destroyed |
| component unmount | route change away from `/watch/:id` | analogous to beforeunload but for SPA navigation |

All three call a shared `flushNow()` helper that:
1. Clears the pending debounce timer.
2. If a pending diff exists, sends the PUT immediately (fire-and-forget; no
   await on `beforeunload`).
3. Resets the pending state.

`beforeunload` uses `navigator.sendBeacon()` if available (it survives the
unload), falling back to `fetch(..., { keepalive: true })`. The fallback path
is best-effort.

### `reset()` semantics

- Immediately calls `DELETE /api/videos/{videoId}/progress`.
- Returns a Promise that resolves on 204, rejects on any error.
- On success, the hook sets `value = null` (so subsequent saves write a fresh
  row, and any `save()` already debounced is cleared).
- On failure, `value` is unchanged; caller (HomePage) shows inline error.

### `videoId === null` semantics

Inert: no fetch, no listeners, `loaded=false`, `value=null`. `save()` and
`reset()` are no-ops.

### `videoId` change semantics

Triggers a fresh load; pending debounced save for the previous video is
flushed first (best-effort), then the hook re-initializes.

---

## Section 8 — Frontend resume sequence

```
                    ┌─────────────────────────────────────┐
                    │ User clicks /watch/:id (or arrives  │
                    │ from HomePage after createJob)      │
                    └──────────────────┬──────────────────┘
                                       │
                                       ▼
                    ┌─────────────────────────────────────┐
                    │ PlayerPage mounts                   │
                    │ - useSubtitleStream(videoId) starts │
                    │ - first poll fires synchronously    │
                    └──────────────────┬──────────────────┘
                                       │
                                       │ data.status arrives
                                       │
                ┌──────────────────────┴───────────────────────┐
                │                                              │
                ▼                                              ▼
        status != completed                           status == completed
                │                                              │
                ▼                                              ▼
  ProcessingLayout / FailedLayout                   CompletedLayout MOUNTS
        (no progress wiring)                                  │
                                                              ▼
                                              ┌───────────────────────────────┐
                                              │ useVideoProgress(videoId)     │
                                              │ fires GET                     │
                                              └────────────────┬──────────────┘
                                                               │
                                                               │ GET resolves
                                                               │ (200 or 404)
                                                               ▼
                                              ┌───────────────────────────────┐
                                              │ loaded=true                   │
                                              │ value=VideoProgress | null    │
                                              └────────────────┬──────────────┘
                                                               │
                                              ┌────────────────┴──────────────┐
                                              │                               │
                                              ▼                               ▼
                                    value === null                   value !== null
                                              │                               │
                                              ▼                               │
                                    no resume; no toast                       │
                                    restoredRef.current=true                  ▼
                                                              ┌───────────────────────────────┐
                                                              │ Wait for                       │
                                                              │ useYouTubePlayer.isReady=true  │
                                                              │ AND restoredRef.current=false  │
                                                              └────────────────┬──────────────┘
                                                                               │
                                                                               │ both conditions met
                                                                               ▼
                                                              ┌───────────────────────────────┐
                                                              │ Resume effect (one-shot):      │
                                                              │ 1. clamp last_played_sec to    │
                                                              │    duration_sec                │
                                                              │ 2. validate last_segment_idx   │
                                                              │    < segments.length;          │
                                                              │    else recompute via binary   │
                                                              │    search on last_played_sec   │
                                                              │ 3. clamp playback_rate to      │
                                                              │    [0.5, 2.0]                  │
                                                              │ 4. seekTo(last_played_sec)     │
                                                              │ 5. setRate(playback_rate)      │
                                                              │ 6. setLoop(loop_enabled)       │
                                                              │ 7. show ResumeToast(...)       │
                                                              │ 8. restoredRef.current=true    │
                                                              └───────────────────────────────┘
```

### Order rationale

- **`useSubtitleStream` first poll → `useVideoProgress` GET**: the order is by
  *component mount*, not by explicit await. `CompletedLayout` is the component
  that owns `useVideoProgress`; it does not mount until `PlayerPage` sees
  `status === 'completed'`. So the GET cannot fire before the stream
  determines completion. No explicit serialization needed.
- **`useYouTubePlayer.isReady` gate**: `seekTo` / `setRate` are no-ops or worse
  before the IFrame player is ready (we observed undefined behavior in Phase 0
  testing). Gate the resume effect on `isReady && !restoredRef.current`.
- **`restoredRef` guard**: a `useRef(false)` outside the effect ensures the
  effect runs *exactly once* per CompletedLayout mount, even if `value`,
  `loaded`, or `isReady` change reactively. This is the same pattern used by
  the Phase 1b TTFS guard.

### State-arrival orderings

The resume effect's correctness depends on six "ready inputs" all being
truthy: `progress.loaded`, `progress.value !== null` (or null with toast
suppressed), `useYouTubePlayer.isReady`, `data.status === "completed"`,
`segments[]` non-empty, and absence of an in-flight stream-reconnect.
Because their arrival order is non-deterministic, the effect MUST behave
identically across permutations.

Six arrival orderings exercised by tests:

1. `loaded` → `isReady` → `segments` → `value` (slow GET, fast IFrame)
2. `isReady` → `value` → `loaded` → `segments` (slow stream)
3. `value` → `loaded` → `isReady` → `segments` (cached progress, IFrame
   slowest)
4. `loaded` (with `value=null`) → `isReady` → `segments` (first-time view)
5. cache-hit completed BEFORE `useVideoProgress` GET resolves — stream
   first poll returns `status="completed"` synchronously; GET resolves
   later with non-null progress
6. stream-reconnect appends segments AFTER `restoredRef.current === true`
   — recompute path would re-fire if not for `restoredRef` guard

In all six, the effect runs at most once and `seekTo` is invoked exactly
once.

**The dep array MUST include `segments` so the recompute path runs against
the latest segments reference.** `restoredRef` is the load-bearing guard
against multi-fire when chunked streaming appends new segments mid-render.
The combination is non-negotiable: removing `segments` from deps means
recompute uses a stale closure; removing `restoredRef` means the effect
re-fires on every segment append.

### Edge cases handled in this sequence

- **First-time view (no progress row)**: `value === null`, `restoredRef`
  flipped immediately, no toast, no resume. The user starts at `t=0` with
  default rate.
- **Cache-hit + first poll already completed + progress null**: same as
  above. Toast does NOT show.
- **Cache-hit + first poll already completed + progress exists**: GET fires,
  resolves to a value, resume runs as normal. Same UX as the streaming path.
- **Player never becomes ready** (network/IFrame failure): resume never runs;
  no harm, no toast. The user can interact with the page and the failure is
  visible via the existing `<VideoPlayer>` loading affordance.

---

## Section 9 — Frontend write sequence

```
┌────────────────────────────────────────────────────────────────┐
│ User-driven event in CompletedLayout                          │
│                                                                │
│ pause   → onPause callback                                     │
│ seek    → useYouTubePlayer state change OR explicit seekTo     │
│ rate    → usePlaybackRate.setRate                              │
│ loop    → setLoop toggle                                       │
└────────────────────────┬───────────────────────────────────────┘
                         │
                         ▼
                 useVideoProgress.save(partial)
                         │
                         ▼
                merge into current state
                         │
                         ▼
              clearTimeout(pending) + setTimeout(flushNow, 1000)
                         │
                         │  …no further save() calls for 1s…
                         ▼
                      flushNow()
                         │
                         ▼
                  PUT /api/videos/{id}/progress
                         │
                         ▼
                204 → console.debug, ignore
                ≠204 → console.warn, ignore
                       (silent per error philosophy)


Force-flush triggers:

visibilitychange=hidden ──┐
beforeunload          ────┼──→ flushNow() (immediate, even if <1s elapsed)
component unmount     ────┘
```

### Mapping events to `save()` calls

| Event source | When fires | `save()` payload |
|---|---|---|
| `useYouTubePlayer.playerState === 2` (paused) | YouTube IFrame state listener | `{ last_played_sec: getCurrentTime(), last_segment_idx: currentIndex }` |
| explicit `seekTo(t)` (prev/next/click-segment) | `goToSegment` callback | `{ last_played_sec: t, last_segment_idx: idx }` |
| `usePlaybackRate.setRate(r)` | speed button click | `{ playback_rate: r }` |
| `setLoop(v)` toggle | loop button click | `{ loop_enabled: v }` |

**Why we do NOT save on `playerState === 1` (playing)**: continuous playback
would fire `save()` every time the player ticks. Save only at user-meaningful
checkpoints (pause / seek / rate / loop). The flush triggers handle the
"close-during-playback" case.

**Why we do NOT auto-save defaults on first ready**: per proposal "Open
question 3", first PUT requires a user-initiated change. A user who opens a
video, presses play, and watches for 5 seconds without changing anything has
no progress row written. They get progress only after the first pause / seek
/ rate / loop. This avoids polluting the history sort with rows that have
default values from videos the user never engaged with.

---

## Section 10 — `ResumeToast` contract

### Props

```ts
interface ResumeToastProps {
  playedAtSec: number;          // for "已恢復到 1:07" formatting
  segmentIdx: number;           // for "(第 18 句)" formatting; 0-indexed internally, 1-indexed in label
  onDismiss: () => void;        // hide self
  onRestart: () => void;        // 「從頭播」button click handler
}
```

### Rendering

```
┌──────────────────────────────────────────────────────────┐
│  ✓ 已恢復到 1:07 (第 18 句)              [從頭播]  [✕]  │
└──────────────────────────────────────────────────────────┘
       ↑                        ↑                ↑      ↑
   green check            formatPlayedAt   formatSegment dismiss
                                              (idx+1)
```

- Position: `fixed bottom-4 right-4` so it does not obscure player controls.
- Backdrop: `pointer-events-none` on the wrapper; only the toast itself
  receives clicks.
- Auto-dismiss: `setTimeout(onDismiss, 5000)` set on mount; cleared on unmount
  AND on click of either button. **5 seconds wall-clock**, never paused
  (proposal "Open question 2").
- 「從頭播」 click: invokes `onRestart` which the parent wires to
  `seekTo(0)` and immediately calls `onDismiss`.
- ✕ click: invokes `onDismiss` directly.

### Formatting helpers

```ts
// Co-located in ResumeToast.tsx (or features/player/lib/format.ts if reused)

function formatPlayedAt(sec: number): string {
  // 67.3 → "1:07"
  // 3725 → "62:05"
  // Always m:ss (no hours; 20-min cap means max 20:00)
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

function formatSegmentLabel(idx: number): string {
  // 17 → "第 18 句" (1-indexed for display)
  return `第 ${idx + 1} 句`;
}
```

### Toast does NOT show when

- `progress` is `null` (first-time view).
- The first-poll cache-hit lands on `completed` AND progress is null.
- The resume effect was skipped because `restoredRef` was already true (e.g.,
  React StrictMode double-mount; covered by the ref).

### Toast DOES show when

- `progress !== null` AND the resume effect runs to completion.
- Always 5 seconds, always wall-clock.

---

## Section 11 — `VideoCard` contract

### Props

```ts
interface VideoCardProps {
  summary: VideoSummary;          // includes optional .progress
  onClick: (videoId: string) => void;
  onReset: (videoId: string) => Promise<void>;  // returns the deleteProgress promise
}
```

### Layout

```
┌──────────────────────────────────────────────────────┐
│ <button> (whole card click)                          │
│  ┌────────────────────────────────────────────────┐  │
│  │  Video title (truncate)                        │  │
│  │  3分27秒 · 4/25                                │  │
│  └────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────┐  │
│  │  ▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░  35%       [重置進度] │  │
│  └────────────────────────────────────────────────┘  │
│  (progress bar + reset button: only when progress)   │
│  (inline red error text shown when reset failed)     │
│ </button>                                            │
└──────────────────────────────────────────────────────┘
```

### Click vs reset event isolation

The progress-bar + reset-button row is rendered as a `<div>` inside the
outer `<button>`. The reset is its own `<button>` element with an `onClick`
that calls `e.stopPropagation()` BEFORE invoking `onReset(videoId)`. Without
`stopPropagation`, the click would bubble to the outer card button and
navigate to `/watch/:id`, which is the opposite of the user's intent.

The reset button also has `type="button"` to prevent form-submit fallout if
the card is ever wrapped in a form.

### Progress-bar formula

```ts
const ratio = Math.min(1, Math.max(0, summary.progress.last_played_sec / summary.duration_sec));
const widthPct = `${(ratio * 100).toFixed(1)}%`;
```

Clamp to `[0, 1]` defends against the edge case where `last_played_sec`
exceeds `duration_sec` despite backend clamping (e.g., a stale client cached
value). The percentage label uses the same clamped ratio.

### Error UI

When `onReset` rejects, `VideoCard` renders an inline red text below the
progress row:

```
重置失敗，請稍後再試
```

The error clears on the next successful action (a click that navigates away,
a successful retry). Implementation: HomePage owns a per-card error map, or
VideoCard manages its own `useState<string | null>(null)` and clears it on
retry. **Decision: VideoCard owns its own error state** — keeps HomePage
simple; the error is per-card-instance and does not need to outlive the
component.

### When progress is `null`

The progress row is not rendered. The card shows only title + duration +
created_at. The reset button is absent.

---

## Section 12 — Sort logic

### SQL

See Section 4. Three-clause ORDER BY:

```sql
ORDER BY
  (p.updated_at IS NULL) ASC,
  p.updated_at DESC,
  v.created_at DESC;
```

### Worked example

Three videos exist:

| video_id | title         | created_at          | progress.updated_at |
|----------|---------------|---------------------|---------------------|
| `aaa…`   | "Video Alpha" | 2026-04-25T10:00Z   | NULL (never played) |
| `bbb…`   | "Video Beta"  | 2026-04-25T09:00Z   | 2026-04-26T08:00Z   |
| `ccc…`   | "Video Gamma" | 2026-04-25T11:00Z   | 2026-04-25T15:00Z   |

Sort breakdown:
- Beta and Gamma both have progress (clause-1 false → ranked above Alpha).
- Among them, Beta's progress is newer (2026-04-26T08:00Z > 2026-04-25T15:00Z),
  so Beta is first.
- Alpha is last; clause-3 doesn't matter (only one without-progress video).

Final order: **Beta → Gamma → Alpha**.

### Multi-without-progress example

| video_id | title    | created_at          | progress |
|----------|----------|---------------------|----------|
| `xxx…`   | "X"      | 2026-04-25T11:00Z   | NULL     |
| `yyy…`   | "Y"      | 2026-04-25T10:00Z   | NULL     |

Both fall to the "without-progress" group (clause-1 true). Clause-2 doesn't
distinguish (both NULL). Clause-3 sorts by `created_at` DESC: **X → Y**.

This matches Phase 0/1b ordering for never-played videos — backward
compatibility for the empty-progress case.

---

## Section 13 — Edge cases & error handling

The proposal's "Edge cases" and "Error-handling philosophy" tables expand to
concrete code paths:

### Stored value out of valid range

| Edge case | Where handled | Code path |
|---|---|---|
| `last_played_sec > duration_sec` | Backend GET (read-side clamp) | `ProgressRepo.get()` reads videos.duration_sec in the same transaction; `min(stored, duration)` returned |
| `last_segment_idx >= len(segments)` | Frontend resume effect | Detected by `segments.length` check; recompute via binary search on `last_played_sec` (same algorithm as `useSubtitleSync`); fallback `idx=0` if all segments are after `last_played_sec` |
| `playback_rate ∉ [0.5, 2.0]` | Frontend resume effect | `clamped = Math.min(2.0, Math.max(0.5, stored))` before `setRate` |

### Network / DB failure

| Operation | Failure | UX response | Code path |
|---|---|---|---|
| GET on mount | network/5xx | silent; `value=null`, `loaded=true` | `useVideoProgress` catches in `try/catch`; `console.warn`; treats as 404 |
| GET on mount | 404 | expected; `value=null`, `loaded=true` | normal path |
| GET on mount | 400 (regex-invalid video_id) | should not happen — caller gates on `videoId !== null` and route-extracted IDs are 11-char | treated same as 5xx |
| PUT on debounce-flush | any non-204 | `console.warn`, no UI; next save overwrites | fire-and-forget; no retry |
| PUT on flush trigger | any non-204 | same | sendBeacon best-effort |
| DELETE on user click | 5xx | inline red error on the card | `onReset` rejects; VideoCard renders error |
| DELETE on user click | 204 | card refetches list; progress disappears | HomePage's `handleReset` calls `fetchVideos()` |

### Concurrent writes

Two browser tabs on the same video both pause within milliseconds:

- Each tab's hook fires PUT with its own merged state.
- Backend processes the two PUTs serially (SQLite is single-writer in WAL
  mode).
- Last-write-wins on `ON CONFLICT DO UPDATE`. The "winner" is determined by
  arrival order, not by `updated_at` value (server stamps both with `now`).
- The UI does not actively reconcile; the next page load reads whichever
  state stuck.

This is acceptable per proposal "Out of scope" #6 (no real-time multi-tab
sync).

### FK CASCADE

- The Phase 2 API never invokes a path that deletes from `videos`. Hard-delete
  is out of scope per proposal §"Out of scope" #5.
- The `ON DELETE CASCADE` on `video_progress.video_id` is a schema-level
  guarantee. It is asserted by a smoke test in `test_lifespan_boot.py`
  (manual DELETE in a transaction shows the progress row disappears) but
  never exercised through the public API.

### Race: GET arrives after unmount

`useVideoProgress` uses an `AbortController` (or a `cancelled` flag — same
pattern as `useSubtitleStream`). After unmount, in-flight GET responses are
discarded; no setState fires.

---

## Section 14 — Acceptance gates

### TTFR (Time to First Resume)

**Definition**: from the click on a `<VideoCard>` (with progress) on
HomePage to the first `seekTo()` call returning. Cache-hit case (no
re-transcribe needed).

**Target**: p95 ≤ 500ms.

**Measurement**: ui-verifier Playwright script:
1. Seed the DB with a completed video + a progress row (`last_played_sec=67`).
2. Open `/`, wait for the card.
3. Install `window.__el_resume_t = null` and patch the page's `seekTo` (via
   `page.addInitScript`) so the first call records `performance.now()`.
4. Capture `t_click = performance.now()` at click.
5. Wait for `window.__el_resume_t` to populate.
6. TTFR = `__el_resume_t − t_click`.
7. Repeat 5 times; report p50 and p95.

The window covers: navigation → PlayerPage mount → useSubtitleStream first
poll (cache-hit completed in <50ms) → CompletedLayout mount →
useVideoProgress GET (200, ~30ms) → useYouTubePlayer.isReady (varies, this is
the dominant term) → seekTo. The 500ms p95 is dominated by IFrame readiness.

### Progress write latency

**Definition**: from the user pause action to the backend receiving the PUT.

**Target**: p95 ≤ 1.5s (1s debounce + ≤500ms write).

**Measurement**: ui-verifier:
1. Open a completed video with no existing progress.
2. Press play; wait 3 seconds.
3. `t_pause = performance.now()`; click pause.
4. Spy on `fetch` for `PUT /api/videos/.../progress`; record arrival time
   `t_put`.
5. Latency = `t_put − t_pause`.
6. Repeat 5 times; report p50 and p95.

### Crash survivability

**Definition**: tab closed within 1s of a pause; next session resumes within
±5s of the pause point.

**Target**: 100% (5/5 trials), pause-point error ≤ 5s.

**Measurement**: ui-verifier:
1. Open video with no progress; play to t=30s; pause.
2. Within 200ms of pause, `page.close()`.
3. Wait 3s for any background flush to complete.
4. New page; navigate to `/watch/:id`.
5. Wait for resume; assert `getCurrentTime() ∈ [25, 35]`.
6. Repeat 5 times.

The `beforeunload` + `sendBeacon` path is the load-bearing mechanism for this
gate.

### Sync precision regression

**Definition**: existing Phase 1a/1b precision metrics (sentence p95 ≤ 100ms,
word p95 ≤ 150ms) under `?measure=1`.

**Target**: no regression vs Phase 1b baseline.

**Measurement**: same ui-verifier `?measure=1` flow as Phase 1b, run on a
completed video both with and without a progress row. Resume affects only
the initial seek; ongoing sync is unrelated to progress.

### Player mount-once invariant

**Definition**: `<VideoPlayer>` mounts exactly once per `/watch/:id` page
load, regardless of progress state.

**Target**: 100%.

**Measurement**: Vitest spy on `<VideoPlayer>` mount callback through the
full `processing → completed → progress-loaded → resumed` lifecycle in
`PlayerPage.streaming.test.tsx` (extended in T11).

---

## Section 15 — Non-goals

The proposal §"Out of scope" enumerates the boundaries; this section
restates them as enforcement targets for spec-reviewer:

- **Per-segment marks** ("I've practiced this sentence") — defer to Phase 3.
- **Multi-device / multi-user sync** — no auth, no user model in Phase 2.
- **Search / filter on history list** — YAGNI.
- **Watch-time analytics** — no separate stats table; out of scope.
- **Hard delete videos** — soft-delete-only per Decision #6.
- **Real-time same-window cross-tab progress sync** — eventual consistency on
  next mount only.
- **Bookmarks / chapters** — Phase 3+.
- **Versioning of `GET /api/videos`** — backward-compatible additive field,
  no `/v2`.
- **Auto-save defaults on first ready** — only after user-initiated change.
- **Pause toast timer when player paused** — always 5s wall-clock.
- **Encryption at rest** — SQLite file is local-only; no PII in progress.
- **Custom retention policy** — progress stays until DELETE or a future hard-
  delete cascade.

A PR that introduces any of the above should be rejected or split into a
separate change.
