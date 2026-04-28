# Capability — Progress API (Phase 2)

## Responsibilities

- Expose three HTTP endpoints under `/api/videos/{video_id}/progress` for
  per-video progress lifecycle: read (`GET`), upsert (`PUT`), and clear
  (`DELETE`).
- Persist progress as one row per video in the `video_progress` table,
  keyed by `video_id` with a foreign key to `videos(video_id)` and
  `ON DELETE CASCADE`.
- Server-stamp `updated_at` on every PUT so that history sort order is
  immune to client-side clock skew.
- Clamp out-of-range stored values on read (`last_played_sec >
  duration_sec`) without rewriting the underlying row.
- Return 204 for both first-time-create and update on PUT; return 204 for
  delete regardless of whether the row exists.
- Distinguish "video does not exist" (PUT 404) from "no progress yet"
  (GET 404).

## Public interfaces

### HTTP endpoints

```
GET    /api/videos/{video_id}/progress
PUT    /api/videos/{video_id}/progress
DELETE /api/videos/{video_id}/progress
```

```python
# backend/app/models/schemas.py

class VideoProgress(BaseModel):
    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: bool
    updated_at: str            # ISO-8601 UTC, server-stamped

class VideoProgressIn(BaseModel):
    """PUT body. `extra="forbid"` rejects `updated_at` and unknown fields."""
    last_played_sec: float
    last_segment_idx: int
    playback_rate: float
    loop_enabled: bool
    model_config = ConfigDict(extra="forbid")
```

### Repository surface

```python
# backend/app/repositories/progress_repo.py

class ProgressRepo:
    def get(self, video_id: str) -> Optional[dict]: ...
    def upsert(
        self, video_id: str, *,
        last_played_sec: float, last_segment_idx: int,
        playback_rate: float, loop_enabled: bool,
    ) -> None: ...
    def delete(self, video_id: str) -> None: ...
```

The repo owns: `video_id` regex validation (via shared
`db._helpers.validate_video_id`), value-range validation (raises
`ValueError`), boolean ↔ INTEGER conversion, and server-stamping of
`updated_at` via `now_iso()`.

## Behavior scenarios

### Endpoint: GET — no progress row exists

GIVEN a `videos` row exists for `video_id == V`
AND no `video_progress` row exists for V
WHEN the client calls `GET /api/videos/V/progress`
THEN the response is `HTTP 404`
AND the body is `{"error_code": "NOT_FOUND", "error_message": "progress not found"}`.

### Endpoint: GET — progress row exists, values within bounds

GIVEN a `videos` row exists for V with `duration_sec == 180`
AND a `video_progress` row exists for V with `last_played_sec=60.0,
last_segment_idx=10, playback_rate=1.25, loop_enabled=1, updated_at="2026-04-25T10:00:00+00:00"`
WHEN the client calls `GET /api/videos/V/progress`
THEN the response is `HTTP 200`
AND the body is the `VideoProgress` shape with `last_played_sec=60.0,
last_segment_idx=10, playback_rate=1.25, loop_enabled=true, updated_at="2026-04-25T10:00:00+00:00"`
AND `loop_enabled` is JSON boolean `true` (not integer `1`).

### Endpoint: GET — last_played_sec exceeds duration is clamped

GIVEN a `videos` row exists for V with `duration_sec == 180`
AND a `video_progress` row exists for V with `last_played_sec=200.0`
WHEN the client calls `GET /api/videos/V/progress`
THEN the response's `last_played_sec` is `180.0` (clamped to duration)
AND the underlying `video_progress` row is unchanged (subsequent direct
SELECT shows `200.0`).

### Endpoint: GET — invalid video_id

GIVEN any state
WHEN the client calls `GET /api/videos/abc/progress` (3-character video_id, fails the 11-character regex)
THEN the response is `HTTP 404`
AND the body is `{"error_code": "NOT_FOUND", "error_message": "progress not found"}`.

### Endpoint: PUT — first-time create

GIVEN a `videos` row exists for V
AND no `video_progress` row exists for V
WHEN the client calls `PUT /api/videos/V/progress` with body
`{last_played_sec: 67.3, last_segment_idx: 17, playback_rate: 1.5,
loop_enabled: true}`
THEN the response is `HTTP 204` with empty body
AND a new `video_progress` row exists for V with the submitted values
AND the row's `updated_at` is a server-stamped ISO-8601 UTC string equal
to or close to the request's processing time
AND a subsequent `GET /api/videos/V/progress` returns the inserted row.

### Endpoint: PUT — update overwrites existing row

GIVEN a `video_progress` row exists for V with values A and `updated_at = T1`
WHEN the client calls `PUT /api/videos/V/progress` with values B
THEN the response is `HTTP 204`
AND the row's values are now B
AND the row's `updated_at` advances to `T2 >= T1` (monotone non-decreasing,
server-stamped).

### Endpoint: PUT — server stamps updated_at, ignores client field

GIVEN a `videos` row exists for V
WHEN the client calls PUT with a body that includes `updated_at:
"1970-01-01T00:00:00Z"` in addition to the four required fields
THEN the response is `HTTP 422` (Pydantic ValidationError) because
`VideoProgressIn` has `extra="forbid"`
AND no `video_progress` row is created.

### Endpoint: PUT — playback_rate below lower bound

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `playback_rate=0.4` and otherwise-valid fields
THEN the response is `HTTP 400`
AND the body is `{"error_code": "VALIDATION_ERROR", "error_message": "<reason mentioning playback_rate>"}`
AND no row is created or modified.

### Endpoint: PUT — playback_rate above upper bound

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `playback_rate=2.5`
THEN the response is `HTTP 400` with `error_code="VALIDATION_ERROR"` and a
message mentioning `playback_rate`.

### Endpoint: PUT — playback_rate at exact bounds is accepted

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `playback_rate=0.5` (lower bound)
THEN the response is `HTTP 204`.

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `playback_rate=2.0` (upper bound)
THEN the response is `HTTP 204`.

### Endpoint: PUT — last_played_sec negative

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `last_played_sec=-0.1`
THEN the response is `HTTP 400` with `error_code="VALIDATION_ERROR"` and a
message mentioning `last_played_sec`.

### Endpoint: PUT — last_segment_idx negative

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `last_segment_idx=-1`
THEN the response is `HTTP 400` with `error_code="VALIDATION_ERROR"` and a
message mentioning `last_segment_idx`.

### Endpoint: PUT — loop_enabled wrong type

GIVEN a `videos` row exists for V
WHEN the client calls PUT with `loop_enabled="yes"` (string, not boolean)
THEN the response is `HTTP 422` (FastAPI default for body parse failure)
AND no row is created or modified.

### Endpoint: PUT — referenced videos row does not exist

GIVEN no `videos` row exists for V
WHEN the client calls `PUT /api/videos/V/progress` with a valid body
THEN the response is `HTTP 404`
AND the body is `{"error_code": "NOT_FOUND", "error_message": "video not found"}`
AND no `video_progress` row is created.

### Endpoint: PUT — invalid video_id regex

GIVEN any state
WHEN the client calls `PUT /api/videos/abc/progress` (3-character video_id)
THEN the response is `HTTP 404`
AND the body is `{"error_code": "NOT_FOUND", "error_message": "video not found"}`.

### Endpoint: PUT — concurrency last-write-wins

GIVEN a `videos` row exists for V
AND no `video_progress` row exists yet
WHEN the client issues two PUT requests back-to-back with values A then B
THEN both responses are `HTTP 204`
AND a subsequent `GET /api/videos/V/progress` returns values B (the second
PUT)
AND the row's `updated_at` corresponds to the second PUT's server-stamp.

### Endpoint: DELETE — existing row

GIVEN a `video_progress` row exists for V
WHEN the client calls `DELETE /api/videos/V/progress`
THEN the response is `HTTP 204`
AND the `video_progress` row no longer exists
AND a subsequent `GET /api/videos/V/progress` returns `HTTP 404`.

### Endpoint: DELETE — no row exists (idempotent)

GIVEN no `video_progress` row exists for V
WHEN the client calls `DELETE /api/videos/V/progress`
THEN the response is `HTTP 204` (idempotent — no error)
AND the table state is unchanged.

### Endpoint: DELETE — invalid video_id regex

GIVEN any state
WHEN the client calls `DELETE /api/videos/abc/progress` (3-character video_id)
THEN the response is `HTTP 404`
AND the body is `{"error_code": "NOT_FOUND", "error_message": "progress not found"}`.

### Endpoint: DELETE — does not affect other rows

GIVEN `video_progress` rows exist for V1 and V2
WHEN the client calls `DELETE /api/videos/V1/progress`
THEN the V1 row is gone
AND the V2 row is unchanged.

### Endpoint: DELETE — does not delete the videos row

GIVEN a `videos` row and a `video_progress` row both exist for V
WHEN the client calls `DELETE /api/videos/V/progress`
THEN the `video_progress` row is gone
AND the `videos` row remains, ready to be played again from t=0
AND any cached `segments` rows for V are unchanged
AND a re-submit of the same YouTube URL hits the cached subtitles
short-circuit.

### Repository: get returns None when no row

GIVEN no `video_progress` row exists for V
WHEN `ProgressRepo(conn).get(V)` is called
THEN it returns `None`.

### Repository: get returns dict with bool conversion

GIVEN a `video_progress` row exists for V with `loop_enabled=1` (INTEGER)
WHEN `repo.get(V)` is called
THEN it returns a dict whose `loop_enabled` is Python `True`
AND a row with `loop_enabled=0` returns `False`.

### Repository: get clamps last_played_sec to duration

GIVEN a `videos` row exists with `duration_sec=120`
AND a `video_progress` row exists with `last_played_sec=200`
WHEN `repo.get(V)` is called
THEN the returned dict's `last_played_sec` is `120.0`
AND a direct `SELECT last_played_sec FROM video_progress` shows `200.0`
(stored value unchanged).

### Repository: get does not clamp when within bounds

GIVEN `duration_sec=120` and `last_played_sec=60`
WHEN `repo.get(V)` is called
THEN the returned dict's `last_played_sec` is `60.0`.

### Repository: get tolerates missing videos row

GIVEN a `video_progress` row exists for V
AND no `videos` row exists for V (degenerate state; should not occur in
production due to FK CASCADE)
WHEN `repo.get(V)` is called
THEN the method does NOT crash
AND it returns the stored `last_played_sec` unchanged (no clamp source
available).

### Repository: upsert validates inputs

GIVEN any valid connection
WHEN `repo.upsert(V, last_played_sec=-1, last_segment_idx=0,
playback_rate=1.0, loop_enabled=False)` is called
THEN it raises `ValueError` mentioning `last_played_sec`
AND no row is inserted.

(Analogous: `last_segment_idx < 0`, `playback_rate < 0.5`, `playback_rate
> 2.0`.)

### Repository: upsert stamps updated_at on every call

GIVEN any sequence of `upsert` calls for the same `video_id`
WHEN each call completes
THEN the row's `updated_at` is set to the server's `now_iso()` at the
moment of the call
AND consecutive calls produce non-decreasing `updated_at` values.

### Repository: upsert validates video_id via shared helper

GIVEN any inputs
WHEN `repo.upsert("abc", ...)` is called (3-character video_id)
THEN the method raises `ValueError` from `validate_video_id`
AND no row is inserted.

### Repository: delete is idempotent

GIVEN any state (row exists or not)
WHEN `repo.delete(V)` is called with a regex-valid `video_id`
THEN the method returns without raising
AND the row for V no longer exists.

### Repository: delete validates video_id

GIVEN any state
WHEN `repo.delete("abc")` is called (regex-invalid)
THEN the method raises `ValueError`.

### Schema: foreign key cascade fires on videos delete

GIVEN a `videos` row and a `video_progress` row both exist for V
AND `PRAGMA foreign_keys=ON` is set on the connection
WHEN `DELETE FROM videos WHERE video_id=?` is executed
THEN the `video_progress` row for V is also gone (CASCADE).

### Schema: primary key collision on duplicate insert

GIVEN a `video_progress` row exists for V
WHEN a raw `INSERT INTO video_progress (video_id, ...) VALUES ('V', ...)`
is executed without `ON CONFLICT … DO UPDATE`
THEN the SQLite engine raises `IntegrityError` (PK collision)
AND the existing row is unchanged.

### Schema: idx_progress_updated_at exists

GIVEN a freshly bootstrapped DB
WHEN the schema is applied
THEN an index `idx_progress_updated_at` exists on
`video_progress(updated_at)` (DESC)
AND the index is used by `list_videos`'s ORDER BY clause (verified by
EXPLAIN QUERY PLAN in a smoke test, optional).

## Invariants

1. **Server-stamped `updated_at`.** Clients MUST NOT supply `updated_at` in
   PUT bodies. The server stamps `now_iso()` on every PUT. This eliminates
   client-clock-skew effects on history sort order.
2. **Read-side clamp only.** `GET` clamps `last_played_sec` to
   `videos.duration_sec` if greater. `PUT` does not clamp; clients submit
   raw values. Re-storing on every read would silently rewrite client
   intent.
3. **404 distinguishes "video missing" from "progress missing".**
   - `GET 404` body: `error_message="progress not found"` (no progress row).
   - `PUT 404` body: `error_message="video not found"` (no videos row).
4. **DELETE is idempotent.** Multiple DELETEs return 204; never 404 for a
   "missing" row (404 only when the `video_id` itself is regex-invalid).
5. **Last-write-wins on concurrent PUTs.** SQLite WAL serializes writers;
   the `ON CONFLICT(video_id) DO UPDATE` makes the second writer overwrite
   the first.
6. **`extra="forbid"` on `VideoProgressIn`.** Unknown fields (including
   `updated_at`) cause Pydantic to reject the body with HTTP 422.
7. **Validation ranges enforced at the repository.** `playback_rate ∈
   [0.5, 2.0]`, `last_played_sec >= 0`, `last_segment_idx >= 0`, all raise
   `ValueError` from `ProgressRepo.upsert`. The router maps `ValueError` to
   HTTP 400 with `error_code="VALIDATION_ERROR"`.
8. **`loop_enabled` storage is INTEGER, exposure is bool.** The repo
   converts `bool ↔ INTEGER` at the boundary; outer interfaces use only
   `bool`.
9. **FK CASCADE is schema-asserted, not API-driven.** Phase 2's API never
   deletes `videos` rows, so the CASCADE is dormant. It is asserted by
   schema-level smoke tests but not by an API scenario.
10. **No middleware mutation.** Authentication, rate limiting, and global
    request rewriting are out of scope; the endpoints accept any
    CORS-allowed origin (localhost) without further checks.

## Non-goals (Phase 2)

- Hard delete of the `videos` row from the progress endpoint.
- Bulk PUT of multiple videos' progress in one request.
- Versioning the response shape (`/v2/.../progress`).
- Server-side push (SSE / WebSocket) of progress changes to other tabs.
- A query parameter to skip the read-side clamp.
- Persistence of historical progress (only the latest is stored — no audit
  trail).
- Authentication or per-user partitioning of `video_progress`.
- A custom `error_code` for "value out of range" beyond
  `VALIDATION_ERROR`; the `error_message` carries the per-field reason.
