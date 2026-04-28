# Phase 2: Video History and Learning Progress Recovery — Tasks

Ordering reflects the dependency graph below. Tasks marked "parallel-eligible"
can be dispatched concurrently with other parallel-eligible tasks as long as
their file sets are disjoint. Tasks marked "sequential" block the next stage
until merged.

```
T01 (schema migration)              ─┐
T02 (ProgressRepo)                  ─┼─→ T04 (progress router)  ─┐
T03 (schemas: VideoProgress)        ─┴─→ T04                     │
                                                                 │
T01 ──→ T05 (videos_repo.list_videos LEFT JOIN + router shape)   │
                                                                 │
T03 ──→ T06 (frontend api/progress.ts)                           │
                                                                 │
T06 ──→ T07 (useVideoProgress hook)                              │
T08 (ResumeToast) — independent                                  │
T09 (VideoCard)   — independent (depends on T03 types only)      │
                                                                 │
T05 + T09 ──→ T10 (HomePage integration)                         │
T07 + T08 ──→ T11 (CompletedLayout integration)                  │
                                                                 │
T01..T11 all green ───────────────────→ T12 (integrator)         │
```

Parallel-eligible groups:
- **Group A (pure backend, no shared files):** T01 (with smoke test), T02, T03.
- **Group B (backend after Group A merges):** T04 (waits T02+T03), T05 (waits T01).
- **Group C (frontend, no shared files):** T08 (independent), T09 (waits T03 schema → propagated as types in T06).
- **Sequential merge points:** T06 (waits T03), T07 (waits T06), T10 (waits T05+T09), T11 (waits T07+T08).
- **Gate:** T12 waits on everything.

Legend:
- **Dependencies** = tasks that must be merged before this one can start.
- **Parallel-eligible with** = tasks that may run concurrently in a different
  implementer dispatch (no overlapping files).
- **Required agents** = must sign off. `tdd-implementer` is always required;
  `spec-reviewer` reviews every task at completion; `ui-verifier` runs at T12
  and on UI-affecting tasks (T08 / T09 / T10 / T11) per CLAUDE.md.

**Pre-flight check (applies to every task T01–T12):**
> tdd-implementer MUST verify `git branch --show-current` returns
> `change/phase2-history-and-resume` before any file change. If on `main`,
> STOP and surface to parent; do not switch or commit.

**Commit message template (every task):**
> `<type>(<scope>): <subject>` per project convention. One task = one commit
> (a separate refactor sub-commit within the same task is allowed if needed).

**Single-file ceiling:** every file listed as touched in a task MUST remain
≤ 200 LOC after the task's changes. Tasks whose green target risks the cap
are flagged inline.

---

## T01 — Schema migration: `video_progress` table + index + smoke test

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T02, T03

**Red tests (write first, in `backend/tests/integration/test_lifespan_boot.py` — extend existing):**

- `test_video_progress_table_exists_after_boot` — open a fresh in-memory DB via
  `get_connection(":memory:")`; assert `SELECT name FROM sqlite_master WHERE
  type='table' AND name='video_progress'` returns one row.
- `test_video_progress_index_exists_after_boot` — assert
  `idx_progress_updated_at` exists.
- `test_video_progress_columns_match_schema` — assert column names + types
  match the DDL in `design.md` §2 (`PRAGMA table_info(video_progress)`).
- `test_video_progress_fk_cascades_on_video_delete` — insert a videos row +
  a video_progress row; `DELETE FROM videos WHERE video_id=?`; assert the
  progress row is gone (CASCADE fires). Requires `PRAGMA foreign_keys=ON`
  which `db/connection.py` already sets.
- `test_video_progress_primary_key_collision_on_duplicate_insert` — insert
  two rows with the same `video_id`; second INSERT raises `IntegrityError`.

**Green implementation:**

- `backend/app/db/schema.sql` (MODIFIED): append the table + index per
  `design.md` §2. Use `IF NOT EXISTS` to keep the bootstrap idempotent
  (`db/connection.py` runs the script once per DB path; the `IF NOT EXISTS`
  guards against repeat in-process bootstraps for `:memory:` connections).

**Refactor note:** none — pure DDL addition.

- **Validates:** `progress-api.md` "Repository: row exists / does not exist"
  scenarios; `design.md` §2 invariants.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(schema): add video_progress table and index`

**Files touched**
- `backend/app/db/schema.sql`
- `backend/tests/integration/test_lifespan_boot.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T02 — `ProgressRepo` get / upsert / delete + validation

- **Pre-flight:** verify branch.
- **Dependencies:** none (the table is created by T01 at boot, but unit tests
  create their own connections via `:memory:`; the test file applies the
  schema by simply calling `get_connection(":memory:")`)
- **Parallel-eligible with:** T01, T03

**Red tests (write first, in `backend/tests/unit/test_repositories_progress.py`, NEW):**

- `test_get_returns_none_when_no_row` — empty table; `get("aaaaaaaaaaa")`
  returns `None`.
- `test_get_returns_row_with_bool_conversion` — insert a row with
  `loop_enabled=1`; assert `repo.get(...)["loop_enabled"] is True` (not 1).
- `test_get_returns_row_with_loop_false` — insert with `loop_enabled=0`;
  assert `is False`.
- `test_get_clamps_last_played_sec_to_videos_duration` — seed videos row with
  `duration_sec=120`, progress row with `last_played_sec=200`; `get` returns
  a dict with `last_played_sec=120`. Stored row is unchanged (verify via
  direct SELECT).
- `test_get_does_not_clamp_when_within_bounds` — `last_played_sec=60`,
  `duration=120` → returned as `60.0`.
- `test_get_returns_clamped_value_even_if_videos_row_missing` — degenerate
  case: progress exists but no videos row (FK was disabled at insert time
  for the test); the repo MUST NOT crash; falls back to returning the stored
  `last_played_sec` unchanged. (Defensive — this should not happen in
  production because FK CASCADE keeps them in sync.)
- `test_upsert_first_time_inserts_row` — empty table; `upsert(...)`; verify
  via SELECT.
- `test_upsert_existing_row_updates_in_place` — insert one row; `upsert` with
  new values; verify SELECT shows the updated values; `updated_at` advances.
- `test_upsert_stamps_updated_at_on_every_call` — call `upsert` twice (with
  a small `time.sleep` if needed); assert second call's `updated_at` >
  first call's.
- `test_upsert_rejects_negative_last_played_sec` — `last_played_sec=-0.1`
  raises `ValueError` with message containing `"last_played_sec"`.
- `test_upsert_rejects_negative_segment_idx` — `last_segment_idx=-1` raises
  `ValueError`.
- `test_upsert_rejects_rate_below_0_5` — `playback_rate=0.49` raises.
- `test_upsert_rejects_rate_above_2_0` — `playback_rate=2.01` raises.
- `test_upsert_accepts_rate_at_exact_bounds` — `0.5` and `2.0` both succeed.
- `test_upsert_validates_video_id_via_shared_helper` — `video_id="abc"`
  (3 chars) raises `ValueError` (re-uses `validate_video_id`).
- `test_upsert_writes_loop_enabled_as_integer_under_the_hood` — upsert with
  `loop_enabled=True`; raw SELECT shows `loop_enabled=1`. Same for `False`
  → `0`.
- `test_delete_removes_existing_row` — insert; `delete`; SELECT count = 0.
- `test_delete_idempotent_on_missing_row` — empty table; `delete("aaa…")`
  returns `None` (no exception).
- `test_delete_does_not_touch_other_rows` — two videos with progress; delete
  one; the other still exists.
- `test_delete_validates_video_id` — invalid id raises `ValueError`.

**Green implementation:**

- `backend/app/repositories/progress_repo.py` (NEW). Target ≤ 120 LOC.
- Reuses `validate_video_id` and `now_iso` from `db/_helpers`.
- `upsert` uses `INSERT … ON CONFLICT(video_id) DO UPDATE SET …` to collapse
  insert/update into a single statement.
- `get` joins `video_progress` with `videos` (LEFT JOIN so the missing-videos
  case returns the stored value):

  ```sql
  SELECT p.*, v.duration_sec
  FROM video_progress p
  LEFT JOIN videos v ON v.video_id = p.video_id
  WHERE p.video_id = ?
  ```

  Then in Python: `clamped = min(p.last_played_sec, v.duration_sec) if
  v.duration_sec is not None else p.last_played_sec`.

**Refactor note:** if the validation block grows past ~15 LOC, extract a
private `_validate_progress_inputs(...)` helper.

- **Validates:** `progress-api.md` repository-layer scenarios.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(repo): add ProgressRepo for video_progress CRUD`

**Files touched**
- `backend/app/repositories/progress_repo.py` (NEW)
- `backend/tests/unit/test_repositories_progress.py` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T03 — `VideoProgress` + `VideoProgressIn` schemas; extend `VideoSummary`

- **Pre-flight:** verify branch.
- **Dependencies:** none
- **Parallel-eligible with:** T01, T02

**Red tests (write first, in `backend/tests/unit/test_schemas.py` — extend existing):**

- `test_video_progress_round_trip` — construct with all fields; JSON dump +
  parse round-trips equal.
- `test_video_progress_in_rejects_updated_at_field` — JSON `{
  last_played_sec: 0, last_segment_idx: 0, playback_rate: 1.0, loop_enabled:
  false, updated_at: "2026-04-25T..."}` parses successfully but the
  `updated_at` field is silently DROPPED (Pydantic v2 default `extra="ignore"`)
  OR raises if we configure `extra="forbid"`. **Decision: configure
  `model_config = ConfigDict(extra="forbid")` on `VideoProgressIn`** so a
  client cannot set `updated_at` even by accident; assert ValidationError.
- `test_video_progress_in_loop_enabled_must_be_bool` — `loop_enabled="yes"`
  raises ValidationError.
- `test_video_summary_progress_defaults_to_none` — construct
  `VideoSummary(video_id, title, duration_sec, created_at)` without
  `progress`; `.progress is None`.
- `test_video_summary_with_progress_field` — construct with `progress=
  VideoProgress(...)`; serializes with the nested progress object.
- `test_video_summary_phase0_field_subset_byte_compatible` — serialize a
  `VideoSummary` with `progress=None` to JSON; selecting only the Phase 0
  keys (`video_id`, `title`, `duration_sec`, `created_at`) yields a value
  byte-equal to a Phase 0 fixture.

**Green implementation:**

- `backend/app/models/schemas.py` (MODIFIED):
  - Add `VideoProgress(BaseModel)` per `design.md` §2.
  - Add `VideoProgressIn(BaseModel)` with `model_config =
    ConfigDict(extra="forbid")`.
  - Extend `VideoSummary` with `progress: VideoProgress | None = None`.
- `backend/app/services/errors.py` (MODIFIED): add `VALIDATION_ERROR =
  "VALIDATION_ERROR"` to the `ErrorCode` enum. No `SAFE_MESSAGES` entry
  (per `design.md` §4).

**Refactor note:** none — schema-only addition.

- **Validates:** `progress-api.md` schema scenarios; `video-history-ui.md`
  list-shape scenario.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(schemas): add VideoProgress and progress field on VideoSummary`

**Files touched**
- `backend/app/models/schemas.py`
- `backend/app/services/errors.py`
- `backend/tests/unit/test_schemas.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T04 — Progress router: GET / PUT / DELETE + integration tests

- **Pre-flight:** verify branch.
- **Dependencies:** T02 (repo), T03 (schemas + ErrorCode.VALIDATION_ERROR)
- **Parallel-eligible with:** T05, T06, T08, T09 (no file overlap)

**Red tests (write first, in `backend/tests/integration/test_progress_router.py`, NEW):**

- `test_get_404_when_no_progress_row` — fixture: videos row exists, no progress;
  `GET /api/videos/{id}/progress` → 404 with body `{error_code:"NOT_FOUND",
  error_message:"progress not found"}`.
- `test_get_404_when_video_id_regex_invalid` — `GET
  /api/videos/abc/progress` (3 chars) → 404 with `error_code="NOT_FOUND"`.
- `test_get_200_returns_progress_shape` — fixture: videos + progress row;
  GET returns 200 with all fields including `updated_at`.
- `test_get_clamps_last_played_sec_when_greater_than_duration` — fixture:
  duration=120, stored last_played_sec=200; GET returns `last_played_sec=120`.
- `test_get_loop_enabled_serialized_as_json_bool_not_int` — stored `1`;
  response JSON shows `"loop_enabled": true` (not `1`).
- `test_put_204_first_time_creates_row` — empty progress table; PUT a valid
  body → 204; subsequent SELECT shows the row with server-stamped
  `updated_at`.
- `test_put_204_update_overwrites_existing_row` — pre-seeded row; PUT new
  values → 204; SELECT shows updated values; `updated_at` advances.
- `test_put_400_when_rate_below_0_5` — body `playback_rate=0.4` → 400 with
  `error_code="VALIDATION_ERROR"` and `error_message` mentioning
  `"playback_rate"`.
- `test_put_400_when_rate_above_2_0` — `playback_rate=2.5` → 400.
- `test_put_400_when_last_played_sec_negative` — 400 with
  `"last_played_sec"` in message.
- `test_put_400_when_last_segment_idx_negative` — 400.
- `test_put_400_when_loop_enabled_not_bool` — body `loop_enabled="yes"` →
  Pydantic ValidationError → 422 (FastAPI default for body parse). Verify
  the body shape; it is acceptable that this case is 422 not 400, document
  in the test.
- `test_put_400_when_extra_field_in_body` — body includes `updated_at`
  (forbidden) → 422 (Pydantic) or 400 (depending on configuration). Match
  whatever `extra="forbid"` produces.
- `test_put_404_when_video_id_does_not_exist_in_videos` — `PUT
  /api/videos/{NEVER_SEEN_ID}/progress` with valid body → 404 with
  `error_code="NOT_FOUND"`, `error_message="video not found"`. The router
  checks the videos row before upsert and rejects if missing.
- `test_put_404_when_video_id_regex_invalid` — 3-char id → 404.
- `test_put_two_back_to_back_last_write_wins` — PUT A; PUT B (different
  values); GET → returns B's values; `updated_at` is the second PUT's
  stamp.
- `test_delete_204_when_row_exists` — pre-seed; DELETE → 204; subsequent GET
  → 404.
- `test_delete_204_when_no_row_exists` — empty table; DELETE → 204
  (idempotent); no error.
- `test_delete_404_when_video_id_regex_invalid` — 3-char id → 404.
- `test_delete_does_not_affect_videos_row` — pre-seed videos + progress;
  DELETE progress; videos row still exists.
- `test_delete_does_not_affect_other_videos_progress` — two videos, both
  with progress; DELETE one; the other's GET still returns 200.

**Green implementation:**

- `backend/app/routers/progress.py` (NEW). Target ≤ 120 LOC.
  - Three handlers: `GET /{video_id}/progress`, `PUT /{video_id}/progress`,
    `DELETE /{video_id}/progress`.
  - GET: call `ProgressRepo.get`; on `None` raise `HTTPException(404, ...)`;
    on dict, construct `VideoProgress(**row)` and return.
  - PUT: parse `VideoProgressIn`; check the videos row exists via
    `VideosRepo(conn).get_video(video_id)`; if missing, raise 404 with
    `"video not found"`; else call `ProgressRepo.upsert(...)`; on
    `ValueError`, raise `HTTPException(400, {error_code:"VALIDATION_ERROR",
    error_message: <reason>})`.
  - DELETE: validate via `validate_video_id` (catch `ValueError` → 404
    `NOT_FOUND`); else call `ProgressRepo.delete`; return 204.
  - All error responses use the `detail=dict` shape that flattens via
    `main.py`'s `http_exception_handler`.
- `backend/app/main.py` (MODIFIED): add `from app.routers import progress as
  progress_router` and `app.include_router(progress_router.router)`.

**Refactor note:** if all three handlers share validation boilerplate, extract
a `_resolve_video_id(video_id)` helper that raises `HTTPException(404)` on
regex failure.

- **Validates:** `progress-api.md` endpoint scenarios.
- **Sequential vs parallel:** sequential after T02+T03.
- **Suggested commit:** `feat(api): add progress GET/PUT/DELETE endpoints`

**Files touched**
- `backend/app/routers/progress.py` (NEW)
- `backend/app/main.py`
- `backend/tests/integration/test_progress_router.py` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T05 — `videos_repo.list_videos()` LEFT JOIN + ORDER BY; router shape

- **Pre-flight:** verify branch.
- **Dependencies:** T01 (table must exist for the JOIN to work)
- **Parallel-eligible with:** T02, T03, T04 (file-disjoint)

**Red tests (write first, in `backend/tests/integration/test_videos_list.py` — extend existing):**

- `test_list_videos_returns_progress_null_when_never_played` — single video,
  no progress; `GET /api/videos` → array of one `VideoSummary` with
  `progress: None`.
- `test_list_videos_returns_nested_progress_when_present` — single video +
  progress row; response has `progress: VideoProgress` with all fields
  (server-stamped `updated_at` included).
- `test_list_videos_with_progress_first_then_without` — three videos: one
  without progress (newest `created_at`), two with progress (older); assert
  the two with-progress come first in the response array.
- `test_list_videos_with_progress_sorted_by_progress_updated_at_desc` —
  three videos all with progress; assert order by `progress.updated_at`
  DESC.
- `test_list_videos_without_progress_sorted_by_created_at_desc` — three
  videos none with progress; assert order matches Phase 0 / Phase 1b
  behavior (created_at DESC).
- `test_list_videos_three_video_mixed_state_example` — exact example from
  `design.md` §12 (Beta with newer progress, Gamma with older progress,
  Alpha never played); assert order is **Beta → Gamma → Alpha**.
- `test_list_videos_loop_enabled_serialized_as_bool_in_nested_progress` —
  insert progress with `loop_enabled=1`; response's nested
  `progress.loop_enabled` is JSON `true` (not `1`).
- `test_list_videos_phase0_consumer_byte_compatible_when_no_progress` —
  with `progress=None` for all rows, the JSON's Phase 0 fields
  (`video_id`, `title`, `duration_sec`, `created_at`) match a Phase 0
  fixture.

**Green implementation:**

- `backend/app/repositories/videos_repo.py` (MODIFIED): rewrite
  `list_videos` to issue the SQL in `design.md` §4. Return type changes
  from `list[sqlite3.Row]` to `list[dict]` where each dict carries the
  joined columns.
- `backend/app/routers/videos.py` (MODIFIED): adjust the response builder
  to construct `VideoSummary(progress=VideoProgress(...) if row contains
  progress fields else None)`. Helper function to keep the comprehension
  readable:

  ```
  def _row_to_summary(row: dict) -> VideoSummary: ...
  ```

  This helper lives in the router module (not the repo), since shaping into
  Pydantic is a router concern.

**Refactor note:** if `_row_to_summary` exceeds ~15 LOC due to the nested
progress conditional, leave it as-is; do not split.

- **Validates:** `video-history-ui.md` "list shape" + "sort" scenarios.
- **Sequential vs parallel:** sequential after T01.
- **Suggested commit:** `refactor(videos): list_videos joins progress and re-sorts`

**Files touched**
- `backend/app/repositories/videos_repo.py`
- `backend/app/routers/videos.py`
- `backend/tests/integration/test_videos_list.py`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T06 — Frontend `api/progress.ts` client + tests

- **Pre-flight:** verify branch.
- **Dependencies:** T03 (schema shape locked); not blocked on T04 (tests use
  MSW; the real router lands in parallel)
- **Parallel-eligible with:** T04, T05, T08, T09

**Red tests (write first, in `frontend/src/api/progress.test.ts`, NEW):**

- `test_get_progress_returns_parsed_value_on_200` — mock GET 200 with full
  body; `getProgress("abc...")` resolves with the parsed object including
  `updated_at`.
- `test_get_progress_returns_null_on_404` — mock GET 404; `getProgress(...)`
  resolves to `null` (NOT throw).
- `test_get_progress_throws_on_5xx` — mock GET 500; `getProgress(...)`
  throws an Error.
- `test_get_progress_throws_on_network_error` — mock fetch rejection;
  throws.
- `test_put_progress_resolves_on_204` — mock PUT 204; `putProgress("abc...",
  {...})` resolves (no return value).
- `test_put_progress_throws_on_400` — mock PUT 400 with
  `{error_code:"VALIDATION_ERROR", error_message:"..."}`; throws an Error
  whose message includes `"VALIDATION_ERROR"`.
- `test_put_progress_throws_on_404` — mock PUT 404 (video not found);
  throws.
- `test_put_progress_sends_correct_body_shape` — assert the request body
  is `JSON.stringify({last_played_sec, last_segment_idx, playback_rate,
  loop_enabled})` — no `updated_at` field.
- `test_delete_progress_resolves_on_204` — mock DELETE 204; resolves.
- `test_delete_progress_throws_on_5xx` — mock DELETE 500; throws.
- `test_delete_progress_resolves_on_404_treated_as_idempotent` — backend
  returns 204 for "no row" but 404 for "invalid video_id"; the test asserts
  the 404 case throws (the caller — VideoCard reset — should never produce
  an invalid id, but defensive).

**Green implementation:**

- `frontend/src/api/progress.ts` (NEW). Target ≤ 80 LOC.

  ```ts
  // (Behavioral description, not implementation. Implementer writes the code.)
  // Three exports:
  //   getProgress(videoId): Promise<VideoProgress | null>
  //   putProgress(videoId, body): Promise<void>
  //   deleteProgress(videoId): Promise<void>
  // Reuses API_BASE from './base'.
  // 404 is normal-path for getProgress (return null); for put/delete it
  // surfaces as a thrown Error.
  ```

- `frontend/src/types/subtitle.ts` (MODIFIED): add `VideoProgress` interface
  matching the backend Pydantic shape; extend `VideoSummary` with
  `progress: VideoProgress | null`.

**Refactor note:** none.

- **Validates:** `progress-api.md` endpoint contract from the client side.
- **Sequential vs parallel:** parallel-eligible (file-disjoint with T04, T05,
  T08, T09).
- **Suggested commit:** `feat(api): add progress client (get/put/delete)`

**Files touched**
- `frontend/src/api/progress.ts` (NEW)
- `frontend/src/api/progress.test.ts` (NEW)
- `frontend/src/types/subtitle.ts`

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T07 — `useVideoProgress` hook + tests

- **Pre-flight:** verify branch.
- **Dependencies:** T06
- **Parallel-eligible with:** T08, T09 (file-disjoint)

**Red tests (write first, in
`frontend/src/features/player/hooks/useVideoProgress.test.ts`, NEW):**

- `test_videoId_null_is_inert_no_fetch_no_listeners` — render with
  `videoId=null`; assert no `getProgress` call; `loaded=false`,
  `value=null`.
- `test_load_on_mount_calls_get_progress` — render with `videoId="abc..."`;
  assert one `getProgress("abc...")` call.
- `test_loaded_flips_to_true_after_get_resolves_200` — mock 200; after
  resolution, `loaded=true`, `value` populated.
- `test_loaded_flips_to_true_after_get_resolves_null_404` — mock returns
  null (404); after resolution, `loaded=true`, `value=null`.
- `test_loaded_flips_to_true_after_get_throws` — mock throws; after
  rejection, `loaded=true`, `value=null` (silent on errors).
- `test_save_debounces_for_1s_then_puts_merged_state` — fake timers; call
  `save({last_played_sec: 67})` at t=0; advance 999ms; no PUT; advance 1ms;
  PUT fires once with the merged body.
- `test_save_coalesces_multiple_calls_within_window` — call `save(A)` at
  t=0, `save(B)` at t=400, `save(C)` at t=800; advance to t=1800; exactly
  ONE PUT fires with merged `A+B+C`.
- `test_save_uses_current_value_as_base_for_merge` — initial `value` from
  GET 200; call `save({playback_rate: 1.5})`; the eventual PUT body
  contains the GET-loaded `last_played_sec` and `last_segment_idx` plus
  the new `playback_rate`.
- `test_save_when_value_is_null_uses_zero_defaults_for_unspecified` — GET
  returned null; call `save({last_played_sec: 30, last_segment_idx: 5})`;
  the merged PUT body has `playback_rate=1.0` (default) and
  `loop_enabled=false` (default).
- `test_visibilitychange_hidden_flushes_pending_save_immediately` — schedule
  a save; before 1s elapses, dispatch `visibilitychange` event with
  `document.visibilityState='hidden'`; assert PUT fires immediately.
- `test_beforeunload_flushes_pending_save_immediately` — dispatch
  `beforeunload` event; PUT fires (use sendBeacon mock if available, else
  fetch with keepalive).
- `test_unmount_flushes_pending_save_immediately` — schedule a save; unmount;
  PUT fires.
- `test_unmount_clears_listeners` — unmount; subsequent dispatch of
  `visibilitychange` does NOT fire any new fetch.
- `test_in_flight_get_discarded_on_unmount` — slow-resolving GET; unmount
  before resolution; no setState fires after unmount (no React warning).
- `test_reset_calls_delete_progress_immediately` — call `reset()`; assert
  `deleteProgress(videoId)` called once.
- `test_reset_resolves_on_204_and_clears_value` — mock DELETE 204; after
  `reset()` resolves, `value=null`.
- `test_reset_rejects_on_5xx_and_keeps_value` — mock DELETE 500; `reset()`
  rejects; `value` unchanged.
- `test_reset_clears_pending_debounced_save` — schedule a save; call
  `reset()` (which DELETEs); after reset resolves, advance past 1s; the
  pending PUT must NOT fire.
- `test_videoId_change_flushes_old_progress_then_loads_new` — render with
  `"a..."`, call `save(...)`; change prop to `"b..."`; assert old PUT fires
  for `"a..."` (best-effort flush), then GET fires for `"b..."`.

**Green implementation:**

- `frontend/src/features/player/hooks/useVideoProgress.ts` (NEW). Target ≤
  150 LOC. **If green target risks the cap**, extract `flushNow` and the
  visibility/beforeunload listener wiring into a small private helper or a
  sibling `useVideoProgress.lib.ts`.
- Implementer follows the contract in `design.md` §7 verbatim:
  - State: `value: VideoProgress | null`, `loaded: boolean`.
  - Refs: `pendingDiff`, `currentMerged`, `debounceHandle`,
    `cancelled`/`AbortController`.
  - `save(partial)`: merge, clear timer, set new timer for 1000ms.
  - `flushNow()`: clear timer, send PUT with merged state, reset diff.
  - Effect on `videoId`: load + listener install + cleanup.
- Defaults for unspecified fields when `value === null` and `save` is called
  with a partial diff:
  - `last_played_sec: 0`
  - `last_segment_idx: 0`
  - `playback_rate: 1.0`
  - `loop_enabled: false`

**Refactor note:** the visibility/beforeunload/unmount triggers all funnel
to `flushNow`; if the wiring exceeds ~25 LOC, extract.

- **Validates:** `player-resume.md` "save events", "flush triggers",
  "reset" scenarios.
- **Sequential vs parallel:** sequential after T06.
- **Suggested commit:** `feat(player): add useVideoProgress hook`

**Files touched**
- `frontend/src/features/player/hooks/useVideoProgress.ts` (NEW)
- `frontend/src/features/player/hooks/useVideoProgress.test.ts` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer

---

## T08 — `ResumeToast` component + tests

- **Pre-flight:** verify branch.
- **Dependencies:** none (pure presentational; types come from already-merged T03/T06)
- **Parallel-eligible with:** T04, T05, T06, T07, T09

**Red tests (write first, in
`frontend/src/features/player/components/ResumeToast.test.tsx`, NEW):**

- `test_renders_played_at_in_m_ss_format` — `playedAtSec=67.3`; rendered
  text contains `"1:07"`.
- `test_renders_segment_label_one_indexed` — `segmentIdx=17` → label
  contains `"第 18 句"`.
- `test_renders_played_at_zero_as_0_00` — `playedAtSec=0` → `"0:00"`.
- `test_renders_played_at_for_long_video` — `playedAtSec=1199.9` →
  `"19:59"` (always m:ss; no hours).
- `test_renders_dismiss_button_calls_onDismiss` — click ✕; `onDismiss`
  called once.
- `test_renders_restart_button_calls_onRestart` — click 「從頭播」;
  `onRestart` called once.
- `test_auto_dismisses_after_5_seconds` — fake timers; mount; advance 4999ms;
  `onDismiss` not called; advance 1ms; `onDismiss` called once.
- `test_auto_dismiss_uses_wall_clock_not_paused_on_player_state` — there is
  no player-state prop; timer runs regardless. (Asserts the proposal's
  Open question 2 decision.)
- `test_dismiss_button_clears_auto_dismiss_timer` — click ✕ at t=2s; advance
  to t=10s; `onDismiss` called exactly once (from the click), not twice.
- `test_restart_button_clears_auto_dismiss_timer` — click 「從頭播」 at t=2s;
  `onRestart` called; advance to t=10s; `onDismiss` called exactly once
  (auto-dismiss is suppressed once the restart action ran). Decision: the
  parent calls `onDismiss` after `onRestart` does its work; we test that
  the toast does not fire the auto-dismiss separately. (If the
  implementation calls `onDismiss` from inside the restart handler, this
  is also valid.)
- `test_unmount_clears_auto_dismiss_timer` — fake timers; mount; unmount at
  t=1s; advance to t=10s; `onDismiss` not called (timer cleared on
  cleanup).
- `test_pointer_events_none_on_backdrop_layer` — assert the wrapper has
  `pointer-events-none` (Tailwind class) so it does not block clicks on
  the player below.
- `test_position_classes_bottom_right` — assert `fixed bottom-4 right-4` (or
  equivalent) classes present.

**Green implementation:**

- `frontend/src/features/player/components/ResumeToast.tsx` (NEW). Target ≤
  80 LOC.
- `formatPlayedAt` and `formatSegmentLabel` defined inline (or extracted to
  `features/player/lib/format.ts` if implementer prefers; either is fine).
- Auto-dismiss via `useEffect(() => { const id = setTimeout(onDismiss,
  5000); return () => clearTimeout(id); }, [onDismiss])`.

**Refactor note:** none expected — small component.

- **Validates:** `player-resume.md` "ResumeToast" scenarios.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(player): add ResumeToast component`

**Files touched**
- `frontend/src/features/player/components/ResumeToast.tsx` (NEW)
- `frontend/src/features/player/components/ResumeToast.test.tsx` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer
- ui-verifier (UI-affecting; smoke-render only at this stage; full coverage
  at T11/T12)

---

## T09 — `VideoCard` component + tests

- **Pre-flight:** verify branch.
- **Dependencies:** T03 / T06 (types — `VideoSummary` with optional
  `progress` field). T06 brings the type into `frontend/src/types/subtitle.ts`.
- **Parallel-eligible with:** T04, T05, T07, T08

**Red tests (write first, in
`frontend/src/features/jobs/components/VideoCard.test.tsx`, NEW):**

- `test_renders_title_and_duration_when_no_progress` — `summary={progress:
  null, duration_sec: 207, ...}`; renders title and `"3分27秒"`.
- `test_does_not_render_progress_bar_when_progress_null`.
- `test_does_not_render_reset_button_when_progress_null`.
- `test_renders_progress_bar_when_progress_set` — `progress.last_played_sec
  =60`, `duration_sec=180`; bar's style width = `33.3%` (or equivalent).
- `test_renders_progress_percentage_label` — same fixture; label includes
  `"33%"` or similar.
- `test_renders_reset_button_when_progress_set` — text "重置進度".
- `test_clamps_progress_bar_when_last_played_sec_exceeds_duration` —
  `last_played_sec=300`, `duration_sec=180`; rendered width clamped to
  `100%`.
- `test_clamps_progress_bar_when_last_played_sec_negative` —
  `last_played_sec=-5`; rendered width is `0%`.
- `test_click_on_card_invokes_onClick_with_video_id` — click the card;
  `onClick("abc...")` called.
- `test_click_on_reset_button_invokes_onReset_with_video_id` — click the
  reset button; `onReset("abc...")` called.
- `test_click_on_reset_button_does_NOT_invoke_onClick` — click reset; the
  card's `onClick` is NOT called (e.stopPropagation).
- `test_reset_button_has_type_button` — assert `type="button"` attribute on
  the reset element (defensive against form-submit in nested forms).
- `test_renders_inline_error_when_onReset_rejects` — `onReset` returns a
  rejected promise; click; the card shows `"重置失敗，請稍後再試"` (or
  similar).
- `test_clears_inline_error_after_successful_retry` — first click rejects;
  error visible; second click resolves; error gone.
- `test_renders_created_at_in_zh_tw_locale` — `created_at="2026-04-25T..."`;
  rendered date includes the locale-formatted day.

**Green implementation:**

- `frontend/src/features/jobs/components/VideoCard.tsx` (NEW). Target ≤ 120
  LOC.
- Outer element: `<button onClick={() => onClick(summary.video_id)}>` (or a
  `<div role="button">` if accessibility is preferred — implementer's
  call). Same Tailwind classes as the existing inline `<button>` in
  `HomePage.tsx` for visual continuity.
- Reset button: nested `<button type="button" onClick={(e) => {
  e.stopPropagation(); onReset(summary.video_id).catch(() => setError("...")); }}>`.

**Refactor note:** if the inline error UI grows past ~10 LOC, extract a
`<ResetErrorMessage>` micro-component; otherwise inline.

- **Validates:** `video-history-ui.md` "VideoCard" scenarios.
- **Sequential vs parallel:** parallel-eligible.
- **Suggested commit:** `feat(home): add VideoCard component with progress + reset`

**Files touched**
- `frontend/src/features/jobs/components/VideoCard.tsx` (NEW)
- `frontend/src/features/jobs/components/VideoCard.test.tsx` (NEW)

**Required agents**
- tdd-implementer
- spec-reviewer
- ui-verifier (smoke-render only)

---

## T10 — `HomePage` integration: VideoCard + reset flow + sort

- **Pre-flight:** verify branch.
- **Dependencies:** T05 (backend list shape), T09 (VideoCard component)
- **Parallel-eligible with:** T11 (different file)

**Red tests (write first, in `frontend/src/routes/HomePage.test.tsx` —
extend existing):**

- `test_replaces_inline_li_with_VideoCard_components` — render with three
  videos; assert three `<VideoCard>` instances rendered (test-id or role).
- `test_clicking_a_card_navigates_to_watch_route` — click card 2;
  `useNavigate` called with `/watch/${id_2}`.
- `test_clicking_reset_button_calls_delete_progress_then_refetches_videos` —
  pre-load with three videos; click reset on the first; assert
  `deleteProgress("...")` called once, then `fetch /api/videos` called a
  second time.
- `test_after_reset_success_progress_field_becomes_null_in_list` —
  pre-load: video A with progress, video B without. Click reset on A.
  After refetch resolves with A.progress=null, assert the rendered list
  re-orders (A moves below B if B is newer, or stays if A is still newer
  by created_at).
- `test_reset_failure_does_not_refetch_list_and_shows_card_error` — click
  reset; mock DELETE rejects; assert `fetch /api/videos` NOT called a
  second time; assert the affected card shows inline error text.
- `test_reset_failure_other_cards_unaffected` — three cards; reset on
  card 1 fails; card 2 and card 3 do not show errors and are still
  clickable.
- `test_empty_state_when_videos_array_is_empty` — list endpoint returns
  `[]`; assert empty-state copy `"貼上 YouTube URL 開始學習"`.
- `test_loading_state_during_initial_fetch` — slow `/api/videos` mock; assert
  no `<VideoCard>` rendered until resolution. (The current HomePage hides
  the list during `loading` for create-job; we keep that.)
- `test_videos_sorted_by_progress_then_created_at` — mock list endpoint
  with the `design.md` §12 example; assert DOM order is **Beta → Gamma →
  Alpha**.

**Green implementation:**

- `frontend/src/routes/HomePage.tsx` (MODIFIED):
  - Import `VideoCard`, `deleteProgress`.
  - Replace the `videos.map((v) => <li>...<button>...</button></li>)` block
    with `videos.map((v) => <VideoCard summary={v} onClick={...} onReset={...} />)`.
  - Define `handleReset(videoId)` that calls `deleteProgress(videoId)`,
    then re-fetches `/api/videos` and replaces local state. Returns the
    promise so VideoCard can `.catch` and surface errors.
  - The card-level error UI is owned by `VideoCard` (per T09); HomePage just
    re-throws.

**Refactor note:** if the click and reset callbacks become repetitive, extract
`useVideoListActions(setVideos)` hook returning `{ handleClick, handleReset }`.

- **Validates:** `video-history-ui.md` end-to-end scenarios (sort, click,
  reset).
- **Sequential vs parallel:** sequential after T05+T09.
- **Suggested commit:** `refactor(home): wire VideoCard with progress reset`

**Files touched**
- `frontend/src/routes/HomePage.tsx`
- `frontend/src/routes/HomePage.test.tsx`

**Required agents**
- tdd-implementer
- spec-reviewer
- ui-verifier (Playwright covers the user-visible flow at T12, but smoke-
  render checks happen here)

---

## T11 — `CompletedLayout` integration: hook + resume effect + toast + save propagation

- **Pre-flight:** verify branch.
- **Dependencies:** T07 (hook), T08 (toast)
- **Parallel-eligible with:** T10 (different file)

**Red tests (write first, in
`frontend/src/features/player/components/CompletedLayout.test.tsx` — NEW;
older `PlayerPage.streaming.test.tsx` may also need MSW handler updates if
it exercises CompletedLayout):**

- `test_calls_useVideoProgress_with_videoId` — render with `videoId="abc..."`;
  assert the hook is invoked with `"abc..."`.
- `test_no_resume_when_value_is_null` — hook returns `{value: null,
  loaded: true}`; isReady=true; `seekTo` is NOT called; no toast in DOM.
- `test_no_resume_until_loaded_true` — hook returns `{value: <obj>,
  loaded: false}`; isReady=true; `seekTo` is NOT called; no toast.
- `test_no_resume_until_isReady_true` — hook returns `{value: <obj>,
  loaded: true}`; isReady=false; `seekTo` is NOT called.
- `test_resume_runs_when_loaded_and_isReady` — hook + isReady both true;
  assert `seekTo(67)` called, `setRate(1.5)` called, loop set to true (if
  stored), and ResumeToast rendered.
- `test_resume_runs_exactly_once_via_restoredRef` — hook + isReady cycle
  true → false → true (e.g., transient IFrame disconnect); `seekTo` called
  exactly once.
- `test_resume_clamps_last_played_sec_to_duration` — `value.last_played_sec
  =200`, `data.duration_sec=180`; `seekTo(180)` called.
- `test_resume_recomputes_segment_idx_when_out_of_range` — `value
  .last_segment_idx=99`, `segments.length=20`; the resume code recomputes
  via binary search on `last_played_sec`. Assert `seekTo` uses
  `last_played_sec` and the toast shows the recomputed `idx + 1`.
- `test_resume_clamps_playback_rate_below_0_5` — stored `0.1`; `setRate(0.5)`
  called.
- `test_resume_clamps_playback_rate_above_2_0` — stored `3.0`; `setRate(2.0)`
  called.
- `test_resume_recompute_segment_falls_back_to_zero_if_no_segment_matches`
  — `last_played_sec=-5` (defensive); recomputes to `idx=0`; toast does
  NOT show (per `design.md` §13).
- `test_toast_does_not_show_when_progress_is_null`.
- `test_toast_dismiss_clears_state` — click ✕; toast unmounts; player
  unaffected.
- `test_toast_restart_button_calls_seek_zero_and_dismisses` — click 「從頭播」;
  `seekTo(0)` called; toast unmounts.
- `test_toast_restart_overwrites_progress_on_next_save_event` — click 「從頭播」
  → `seekTo(0)` → user pauses (`save({last_played_sec: 0,
  last_segment_idx: 0})`); after debounce, PUT body has `last_played_sec=0`.
- `test_pause_event_calls_save_with_position_and_segment_idx` — simulate
  player state change to paused at currentTime=42, currentIndex=10; assert
  `save({last_played_sec:42, last_segment_idx:10})` called.
- `test_seek_event_via_goToSegment_calls_save` — call `handleClickSegment(5)`;
  assert `seekTo` invoked AND `save({last_played_sec: <segment.start>,
  last_segment_idx: 5})` called.
- `test_rate_change_calls_save_with_playback_rate` — change rate to 1.5;
  assert `save({playback_rate: 1.5})`.
- `test_loop_toggle_calls_save_with_loop_enabled` — toggle loop on; assert
  `save({loop_enabled: true})`.
- `test_save_NOT_called_before_isReady` — initial render with isReady=false;
  no `save` call even if rate state changes during render.
- `test_save_NOT_called_during_initial_resume` — the resume effect's own
  `setRate`/`setLoop` calls do NOT trigger a self-save loop. The
  `restoredRef`-guarded effect runs first; subsequent rate/loop changes are
  user-driven and do save.
- `test_unmount_propagates_through_useVideoProgress_flush` — unmount the
  component; the hook's internal `flushNow` runs (existing in T07); covered
  by the hook's test, but smoke-asserted here via spy on `putProgress`.
- `test_existing_phase1a_behaviors_unaffected` — `useSubtitleSync`,
  `useAutoPause`, `useLoopSegment`, `usePlaybackRate`, `useKeyboardShortcuts`
  all still mount and produce expected behavior. (Smoke; the dedicated
  tests for those hooks remain green.)

**Green implementation:**

- `frontend/src/features/player/components/CompletedLayout.tsx` (MODIFIED).
  Target ≤ 200 LOC. **If green target risks the cap**, extract:
  - `useResumeOnce(progress, isReady, segments, seekTo, setRate, setLoop)`
    into `hooks/useResumeOnce.ts` (the resume effect + restoredRef +
    clamping/recompute helpers).
  - The "save propagation" wiring (mapping playerState/seek/rate/loop to
    `progress.save`) into the same hook or into a sibling
    `useProgressSaveBridge`.
  - This extraction is a refactor sub-commit within T11.
- Wiring summary (per `design.md` §8 + §9):
  1. `const progress = useVideoProgress(videoId);`
  2. `const restoredRef = useRef(false);`
  3. Resume effect on `[progress.loaded, progress.value, isReady,
     segments]`: when `loaded && value && isReady && !restoredRef.current`,
     run the resume sequence; set `restoredRef.current = true`; setShowToast.
  4. When `loaded && value === null`, also flip `restoredRef.current = true`
     to suppress future re-runs and skip toast.
  5. Save propagation: extend existing pause / seek / rate / loop callbacks
     to call `progress.save(...)` AFTER `restoredRef.current === true`.
  6. Mount `<ResumeToast>` conditionally on `showToast`.

**Refactor note:** the high-risk file in this phase. Implementer should run
the simplify pass after green to consolidate any duplicated code between the
resume path and the save-propagation path before spec-reviewer enters.

- **Validates:** `player-resume.md` end-to-end scenarios.
- **Sequential vs parallel:** sequential after T07+T08.
- **Suggested commit:** `refactor(player): wire useVideoProgress + ResumeToast in CompletedLayout`

**Files touched**
- `frontend/src/features/player/components/CompletedLayout.tsx`
- `frontend/src/features/player/components/CompletedLayout.test.tsx` (NEW)
- (optional, if LOC budget forces) `frontend/src/features/player/hooks/useResumeOnce.ts`
- (optional) `frontend/src/routes/PlayerPage.streaming.test.tsx` (MSW handler
  update to mock `/api/videos/.../progress` GET → 404 by default for
  existing tests that do not exercise progress)

**Required agents**
- tdd-implementer
- spec-reviewer
- ui-verifier (smoke at this stage; full TTFR / write-latency / crash gates
  at T12)

---

## T12 — Integrator gate: full test sweep, lint, build, ui-verifier, archive, PR

- **Pre-flight:** verify branch.
- **Dependencies:** T01–T11 all merged and green on their individual tests
- **Parallel-eligible with:** none

**Acceptance criteria**

- `cd backend && python -m pytest` green (all units + integrations,
  including new `test_repositories_progress.py`,
  `test_progress_router.py`, extended `test_videos_list.py`,
  `test_lifespan_boot.py`, extended `test_schemas.py`).
- `cd frontend && npx vitest run` green (all suites including
  `progress.test.ts`, `useVideoProgress.test.ts`, `ResumeToast.test.tsx`,
  `VideoCard.test.tsx`, extended `HomePage.test.tsx`,
  `CompletedLayout.test.tsx`, plus untouched
  `useSubtitleSync.*`, `useLoopSegment.test.ts`, `usePlaybackRate.test.ts`,
  `useAutoPause.test.ts`, `useKeyboardShortcuts.test.ts`,
  `PlayerPage.measure.test.tsx`, `PlayerPage.streaming.test.tsx`).
- `cd frontend && npm run lint` clean.
- `cd frontend && npm run build` succeeds.
- **200-line scan** — no `.py`/`.ts`/`.tsx` file over 200 lines across
  `backend/app` + `frontend/src`.
- ui-verifier agent boots real dev servers (backend on 8000, frontend on
  5173), drives Playwright through the Phase 2 flows, and produces
  `docs/ui-verification/phase2-history-and-resume.md` with PASS on:
  - **TTFR (time-to-first-resume)**, p95 ≤ 500ms over 5 trials, per
    `design.md` §14.
  - **Progress write latency** ≤ 1.5s p95 over 5 trials, per `design.md`
    §14.
  - **Crash survivability**: 5/5 trials, pause-point error ≤ 5s, per
    `design.md` §14.
  - **Sync precision regression check**: sentence p95 ≤ 100ms, word p95 ≤
    150ms with `?measure=1` (Phase 1b baseline preserved).
  - **Player mount-once invariant**: `<VideoPlayer>` mounts exactly once
    across the `processing → completed → resume` flow.
  - **HomePage sort**: a fixture with three videos in the §12 example
    state renders in the correct order.
  - **Reset flow**: clicking 重置進度 calls DELETE, refetches, re-orders
    the list.
  - **Toast 5s wall-clock**: toast appears, persists 5s, dismisses.
  - **Toast does not appear for first-time view**: pristine progress state
    (404 GET) on a video; resume effect runs, no toast.
- `openspec/changes/phase2-history-and-resume/` is moved to
  `openspec/archive/phase2-history-and-resume/` per AGENTS.md convention,
  and `CLAUDE.md` phase roadmap is updated to mark Phase 2 complete.
- PR opened against `main` with the archive move + ui-verifier report
  committed. PR title: `Phase 2: Video History and Learning Progress
  Recovery`. PR body includes: acceptance-gate table (TTFR, write latency,
  crash survivability, sync regression all PASS), pytest/vitest/lint/build
  result summary, link to
  `docs/ui-verification/phase2-history-and-resume.md`.

**Files touched**
- `docs/ui-verification/phase2-history-and-resume.md` (NEW)
- `openspec/archive/phase2-history-and-resume/**` (moved from
  `openspec/changes/...`)
- `CLAUDE.md` (roadmap row for Phase 2 marked complete)

**Required agents**
- ui-verifier (final gate)
- integrator (archive move + PR)
- spec-reviewer (final sign-off)

**Suggested commit(s):**
- `docs(ui-verification): phase2 history and resume report`
- `chore(archive): archive phase2 spec after integration`

---

## Open questions — all resolved

Per the proposal's three "Open questions" recommendations, every decision is
locked before T01 starts:

1. **List endpoint backward-compat (no versioning)** — `VideoSummary.progress`
   is an additive optional field; consumers reading only Phase 0 fields are
   byte-compatible. Validated by `test_video_summary_phase0_field_subset_byte_compatible`
   and `test_list_videos_phase0_consumer_byte_compatible_when_no_progress`.
2. **Toast 5s wall-clock** — `ResumeToast` uses a single `setTimeout` not
   coupled to player state. Validated by
   `test_auto_dismiss_uses_wall_clock_not_paused_on_player_state`.
3. **Defaults not auto-recorded** — first PUT only after a user-initiated
   change (pause / seek / rate / loop). The save propagation in T11 happens
   only after `restoredRef.current === true` AND only on the four event
   types listed in `design.md` §9. Validated by
   `test_save_NOT_called_before_isReady` and the absence of a "first ready"
   save trigger in T11.

### Decisions absorbed from `design.md`

- **`extra="forbid"` on `VideoProgressIn`** — server rejects `updated_at` in
  PUT body (T03 test `test_video_progress_in_rejects_updated_at_field`).
- **PUT 404 distinction** — "video not found" vs "progress not found"
  separately enumerated; T04 covers both.
- **Read-side clamp on `last_played_sec`** — backend clamps in
  `ProgressRepo.get()` only; PUT writes raw values (T02 tests).
- **Frontend recompute of `last_segment_idx`** — when out of range, recompute
  via binary search on `last_played_sec`; fallback `idx=0` if all segments
  are after `last_played_sec` (T11 tests).
- **Frontend rate clamp** — `[0.5, 2.0]` clamp before `setRate` (T11).
- **`sendBeacon` fallback** — preferred for `beforeunload`; `fetch
  keepalive: true` if unavailable (T07 leaves implementation choice to the
  implementer; both paths are testable with mocks).
- **VideoCard owns its own error state** — keeps HomePage simple (T09).
- **Reset clears pending debounce** — `useVideoProgress.reset()` cancels any
  pending PUT before sending DELETE (T07 test
  `test_reset_clears_pending_debounced_save`).

No open questions remain for implementer dispatch.
