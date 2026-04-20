# Review: phase0-refactor — T02 (SQLite infrastructure)

**Date**: 2026-04-17
**Reviewed**: Code (post-implementation review; spec already approved in T02 spec review)
**Commit**: `ccd728f` (on `change/phase0-refactor`)
**Prior commits on branch**: `727914c` (T01) → `d431c6d` (T01 patch) → `ccd728f` (T02)
**Verdict**: **APPROVE** (with notes — no Critical issues)

---

## Summary of numbers

- Pytest: **94 passed, 2 skipped** — matches `d431c6d` baseline. Skipped tests are the T01 conditional `test_fake_signatures.py::Test*VsRealClient` (`find_spec(...) is None` → `pytest.skip(...)` with explanatory message, not an error-skip).
- New repo tests alone: **47 passed, 0 skipped, 0.08s**.
- `from app.routers.subtitles import router` still imports cleanly → old pipeline untouched.
- File sizes (all ≤ 200-line rule):
  | file | lines |
  |---|---|
  | `app/db/schema.sql` | 30 |
  | `app/db/connection.py` | 32 |
  | `app/repositories/jobs_repo.py` | 170 |
  | `app/repositories/videos_repo.py` | 133 |
  | `tests/unit/test_repositories_jobs.py` | 197 |
  | `tests/unit/test_repositories_videos.py` | 199 |
  | `tests/unit/test_repositories_monotonicity.py` | 163 |

---

## Verification of reported deviations

1. **Schema verbatim**: PASS. Byte-level `diff` against the fenced SQL block in `design.md` §2 returns zero differences. `IF NOT EXISTS` has been correctly removed; everything else (column order, `CHECK` constraint, index, composite PK) matches.
2. **Test file split (3 files, all ≤200L)**: PASS. Responsibility split is coherent (jobs CRUD / videos CRUD+atomicity / concurrency+monotonicity).
3. **Atomic publish failure test via subclass override**: PASS. `BoomRepo` overrides `_insert_segments` to raise after the `videos` upsert has already executed within the `with self._conn:` block. Independently verified: after `RuntimeError`, both `videos` and `segments` tables have 0 rows. Rollback is genuine (the context manager commits or rolls back the implicit transaction — not a fake assertion).
4. **WAL concurrency uses `tempfile` file-based DB**: PASS. `_make_file_db()` uses `tempfile.NamedTemporaryFile(suffix='.db')`; `PRAGMA journal_mode=wal` is confirmed applied (I verified on a file DB). `:memory:` fixture correctly skips WAL (unsupported on memory DBs) — the skip is documented in the conftest docstring.
5. **`JobsRepo` per-instance `threading.Lock`**: PRESENT. Serializes read-then-write inside one instance. See Architecture notes below — this is fine for now but has a latent gotcha for T03/T04.
6. **`conftest.py` docstring**: UPDATED and accurate — now says "WAL mode is skipped for in-memory DBs; each call creates a fresh `:memory:` connection."

---

## Issues Found

### Critical
_None._

### Medium

- **🟡 M1 — Per-instance lock does not serialize across multiple `JobsRepo` instances sharing one connection.**
  File: `backend/app/repositories/jobs_repo.py:41` (`self._lock = threading.Lock()`).
  Observation: I constructed two `JobsRepo(conn)` from the same `conn` and confirmed `r1._lock is r2._lock` is `False`. The T02 concurrency tests all build exactly one `JobsRepo` per test, so the issue is invisible today — but the pattern is a footgun for T04 (`JobRunner.submit()`), which could reasonably create a fresh repo per call if the author copies the fixture style. Two threads each with their own `JobsRepo` pointing at the same `sqlite3.Connection` would race on the `read current → write max(current, new)` sequence. At worst, a lower value could clobber a higher one despite the docstring promise.
  Recommendation (pick one for T03/T04 spec):
    1. Make `_lock` a module-level singleton keyed by `id(conn)`, OR
    2. Document that callers MUST hold exactly one `JobsRepo` per connection, and enforce that in `JobRunner` (wire a single shared repo through a FastAPI dependency), OR
    3. Replace the Python-level read-then-write with a `sqlite3` conditional UPDATE (`UPDATE jobs SET progress=? WHERE job_id=? AND progress<=?`) so atomicity is delegated to SQLite — this also eliminates the need for the lock entirely in production (tests can still use strict mode as a separate check with `SELECT … FOR UPDATE` emulation).
  Severity rationale: T02 itself is fine. But this is the kind of constraint that silently breaks when T04 lands. Flagging now so T04's spec pre-empts it.

### Low

- **🟢 L1 — `update_status` accepts arbitrary `error_code` strings.**
  File: `backend/app/repositories/jobs_repo.py:92`.
  Observed: `r.update_status('j1', 'failed', error_code='ANYTHING_REALLY', error_message='a' * 10000)` stores everything verbatim. The SQL schema is `TEXT` with no `CHECK`. `design.md` §4 enumerates a closed set of codes (`INVALID_URL`, `VIDEO_UNAVAILABLE`, `VIDEO_TOO_LONG`, `FFMPEG_MISSING`, `WHISPER_ERROR`, `TRANSLATION_ERROR`, `INTERNAL_ERROR`).
  Recommendation: either define a `Literal[...]` typed constant (or `Enum`) for `error_code` at the repo boundary, or accept that the pipeline layer will be the gatekeeper. Document the decision. Not blocking — schema-level enum enforcement is cheap but not in the T02 acceptance criteria.
  Severity rationale: The spec explicitly lists `error_code` as typed in the pipeline; repo is a dumb writer. Fine for now; flag for T03 when pipeline writes real codes.

- **🟢 L2 — `sweep_stuck_processing` test uses `older_than_sec=0.0`, which is a boundary value that sweeps *all* processing rows regardless of age.**
  File: `backend/tests/unit/test_repositories_jobs.py:166`.
  The happy-path test sweeps with threshold `0.0` and asserts `count >= 1`. Because `cutoff = now - 0s = now` and `updated_at < now` is essentially always true by the time the UPDATE fires, this test doesn't exercise the actual age arithmetic. The counter-test (`test_sweep_skips_recently_started` with `older_than_sec=3600`) does lock down the other side of the boundary. Together they fence the behavior, but neither proves the arithmetic on a realistic threshold (e.g., 0.1s + sleep).
  Recommendation: optional — add one test with `time.sleep(0.15)` between `update_status('processing')` and `sweep_stuck_processing(older_than_sec=0.1)` to prove real elapsed-time filtering. T04 will build on this; catch it there if not here.

- **🟢 L3 — `list_videos` does not verify ordering when rows share the same `created_at`.**
  File: `backend/app/repositories/videos_repo.py:120`.
  Since `created_at` is ISO timestamp with microseconds, two back-to-back `publish_video` calls in the same process *can* collide (rare, but deterministic under frozen clocks). Test `test_list_videos_ordered_by_created_at_desc` runs two publishes without any clock guarantee, relies on wall-clock difference, and would become flaky under a frozen `_now`. Not a T02 bug — just worth noting.

- **🟢 L4 — `sweep_stuck_processing` uses `RETURNING` clause.**
  File: `backend/app/repositories/jobs_repo.py:127`.
  `RETURNING` on `UPDATE` requires SQLite ≥ 3.35 (2021-03-12). Bundled Python sqlite3 on Python 3.9 on macOS / Linux is typically fine, but if the deployment pins an old SQLite (e.g., Alpine-based containers with an older `libsqlite`), this breaks silently. Alternative: use `cursor.rowcount` after the UPDATE. Not a T02 failure; just visible tech debt.

---

## Architecture Review

- **Schema verbatim**: ✅ byte-level match with `design.md` §2.
- **Layering**: ✅ clean. `db/` → `repositories/` → (future `services/`). Repos hold no service logic; they are thin SQL wrappers. No router or service imports `sqlite3` directly.
- **Atomic publish**: ✅ single transaction via `with self._conn:` context manager wrapping the upsert, delete, and `executemany`. Verified rollback includes the `videos` row, not just segments. This correctly implements design.md §2 "Option A".
- **200-line rule**: ✅ every new file within budget.
- **Progress ladder**: not implemented here (that's pipeline-level), but `update_progress` correctly enforces monotonicity, which is the T02 contract.
- **Extensibility**: the `_insert_segments` extraction (done for failure injection) is a slight test-smell — production code bends for test-ability. Acceptable given that `executemany` is a C built-in and can't be monkeypatched. Document it with a comment; flag if this pattern spreads.

## QA Review

All T02 acceptance criteria from `tasks.md` are met:
- ✅ Every public method happy path covered.
- ✅ `test_update_progress_lowering_raises_in_strict_mode` — autouse `EL_TEST_STRICT=1` makes `pytest.raises(AssertionError)` fire on lowering.
- ✅ `test_update_progress_lowering_logs_warn_in_production_mode` — `monkeypatch.delenv("EL_TEST_STRICT", raising=False)` + `caplog.at_level(WARNING)` + unchanged stored value. Verified the `logger.warning(...)` path is live.
- ✅ WAL concurrency test: 2 threads on 2 distinct `job_id`s, real file-based DB, barrier-synchronized, 200ms wall-clock budget. Passed locally in < 10ms.
- ✅ Multi-thread progress monotonicity: strict + production mode variants, both assert final stored progress equals max attempted.
- ✅ Atomic publish failure: videos AND segments both verified empty (not just videos).
- ✅ `video_id` regex rejected *before* SQL: independently verified — `ValueError` fires before any connection state change; row counts stay at 0 across all four malformed IDs.
- ✅ `sweep_stuck_processing(older_than_sec=...)` has happy path, boundary (3600s skip), and non-processing ignore. Age arithmetic could use one realistic-threshold test (L2 above).

Unhappy paths that ARE covered:
- Malformed `video_id` → raises before SQL.
- Lowering progress in strict mode → raises.
- Lowering in production → no-op + WARN log.
- Transaction failure mid-publish → full rollback.
- Sweep on non-processing rows → untouched.

Unhappy paths NOT covered (acceptable — out of T02 scope or handled upstream):
- `update_status` with invalid status string → SQLite's CHECK constraint raises `IntegrityError`. Not tested in repo; spec relies on Python-layer enum enforcement (Medium L1).
- `publish_video` with empty `segments=[]` — one test path uses this implicitly. `executemany` on empty list is a no-op; no explicit positive test. Low.

## Security Review

- **`video_id` regex** enforced at repo boundary for every write method and for `get_video`, `get_segments`. `find_active_for_video` does NOT validate — reasonable (read-only parameterized query), but inconsistent with the write methods. Not a security issue because `?` placeholder prevents injection; inconsistent but harmless.
- **SQL injection**: all queries use `?` placeholders, including `executemany` in `_insert_segments`. No f-string / `%` formatting on SQL. `title`, `source`, `text_en`, `text_zh`, `words_json` all go through placeholders. ✅
- **Traversal prevention**: `video_id` composing filesystem paths is a T03 concern; T02's regex validation already gates at the repo layer, which is the correct defense-in-depth point.
- **PRAGMA application**: verified on two sequential connections to the same file — both get `journal_mode=wal` and `foreign_keys=1`. ✅
- **`check_same_thread=False`**: intentional (threaded access), lock in `JobsRepo` compensates inside one instance — but see M1 for the multi-instance gap.
- **`words_json`**: stored via `json.dumps(seg["words"])`. If a future adversarial word list contained backslashes or control bytes, json-encoding is safe. ✅
- **Secrets / credentials**: none touched.

## I1 (T01 conditional tests) status

- `TestFakeWhisperVsRealClient::test_transcribe_signature_matches_real` → SKIPPED (correct `find_spec("app.services.transcription.whisper") is None → pytest.skip("... will activate in T03")`).
- `TestFakeTranslatorVsRealClient::test_translate_batch_signature_matches_real` → same pattern, same skip reason.
- Both are conditional skips, not error-skips. Will automatically flip to PASS/FAIL when T03 lands the real modules.

## Recommendations

1. **Proceed to T03.** No follow-up patch required. All Critical-class risks are resolved; M1/L1–L4 are best addressed in the T03 spec rather than a T02 follow-up.
2. **Fold M1 into T03's spec preamble**: `JobRunner` and pipeline code must share a single `JobsRepo` instance per connection, OR the spec should require swapping `update_progress` to a conditional UPDATE (`WHERE progress <= ?`) that does not need a Python-level lock.
3. **Fold L1 into T03's pipeline spec**: introduce an `ErrorCode` `Literal` / `Enum` that pipeline passes to `jobs_repo.update_status`. Repo stays dumb; types enforce at call sites.
4. **Optional future hygiene**: consider adding a sweep test with real elapsed time (L2) when T04 lands, and replacing `RETURNING` with `rowcount` (L4) if deployment targets older SQLite.

---

**Verdict**: **APPROVE**. T02 is clean, verbatim, atomically correct, and well-tested. Medium M1 is a forward-looking concern that should shape T03's spec, not a T02 regression. Safe to proceed to T03.
