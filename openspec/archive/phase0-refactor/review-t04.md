# Review: phase0-refactor — T04 Jobs runner (ThreadPoolExecutor + lifespan)

**Date**: 2026-04-17
**Reviewed**: Code (commits `6fcd2ba` T02 M1 fix + `3d34bb4` T04 runner) against `design.md` §§2,4, `specs/jobs-api.md`, `specs/data-layer.md`, `review-t02.md` M1
**Verdict**: **NEEDS_CHANGES** (2 Critical defects uncovered by T04 lifespan wiring; both are carried over from T02 but must be fixed before T04 is callable)

## Executive summary

- **Pytest**: 133 passed, 0 skipped, 0 failed (0.87s). `TestCrossInstanceMonotonicity::test_two_distinct_instances_max_wins` and the four `TestRunnerSubmit` cases all green.
- **File sizes**: runner.py 136L; jobs_repo.py 182L; main.py 34L; pipeline.py 193L. All under the 200-line ceiling.
- **Implementer's T02 M1 deviation**: the user's brief framed the Python-level shared lock as "the implementer's chosen path." I examined the commits and found the implementer actually applied **BOTH** remedies: commit `6fcd2ba` landed the SQL-level conditional UPDATE (`WHERE progress <= ?`) exactly as review-t02 M1 recommended, and commit `3d34bb4` additionally introduced the per-connection shared Python lock. The SQL fix is the load-bearing mechanism; the Python lock is belt-and-suspenders. Verified empirically below.
- **However**, T04's lifespan wiring exposes two pre-existing T02 bugs that now bite at app startup: a wrong `_DB_PATH` walk and missing schema-application in `get_connection()`. Both make the lifespan crash. Either one would fail a fresh-clone first-run — which is a Phase 0 DoD line item.

## Technical adjudication: Python-per-connection lock — is it safe?

**Short answer**: yes, and in any case it is not load-bearing. The SQL conditional UPDATE alone is sufficient for cross-connection monotonicity. Production correctness does not depend on connection identity.

**Evidence**:
- Reproduced the M1 race by constructing two `JobsRepo(c1)` and `JobsRepo(c2)` where `c1 is not c2` (distinct file-DB connections, distinct `id(conn)`, distinct locks), issuing interleaved `update_progress(30)` / `update_progress(80)` from two threads with a barrier. Final stored progress: **80** (the max). The lower write landed as "conditional no-op: ... DB has higher" per the logger. SQLite's writer serialization plus `WHERE progress <= ?` closes the race without any Python lock.
- `6fcd2ba`'s diff shows `UPDATE jobs SET progress=?, updated_at=? WHERE job_id=? AND progress<=?` — exactly the review-t02 M1 recommendation.
- `TestCrossInstanceMonotonicity` validates the exact scenario the M1 flagged and passes.

**Production connection sharing** (verified by code reading, not assumption):
- `get_connection()` does **not** cache — every call returns a fresh `sqlite3.Connection`. `c1 is c2 → False`.
- `_default_pipeline_run` → module-level `pipeline.run(job_id)` → opens its own `get_connection()`. `Pipeline.__init__` then constructs `JobsRepo(conn)` and `VideosRepo(conn)` sharing that one connection.
- `JobRunner._get_repo()` (lazy) calls `get_connection()` independently, so the runner's repo and the pipeline's repo point at **different** connections. Hence **different** Python locks. This would break the old per-instance-lock design, but does NOT break the current SQL-conditional design.
- Runner's `_fail_job` writes `update_status('failed', ...)` only after `_pipeline_run_fn` has raised and returned — i.e. sequentially with the pipeline's own writes, so there is no concurrent writer race on the job row. Safe.

**Conclusion on the deviation**: acceptable. The Python lock is redundant but harmless. See Minor M1 for cleanup recommendation.

## Issues found

### Critical (block T05)

#### C1. `get_connection()` default DB path walks one `.parent` too many

- **File**: `backend/app/db/connection.py:13`
  ```python
  _DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "echolearn.db"
  ```
- `connection.py` lives at `backend/app/db/connection.py`. Four `.parent` calls resolve to the **project root** (`/Users/si/Code/Vibe/EchoLearn/`), then append `data/echolearn.db`. Observed path: `/Users/si/Code/Vibe/EchoLearn/data/echolearn.db`.
- Design (`design.md` §1) and `ui-verifier.md` (`backend/data/echolearn.db`) both expect the DB to live inside `backend/`. A fresh clone does not have an `EchoLearn/data/` directory; only `backend/data/cache/` exists.
- **Reproduction**: started a fresh `lifespan(app)` context → `OperationalError: unable to open database file`.
- **Fix**: three `.parent` calls instead of four.
- **Why it's Critical now (not flagged in T02)**: T02 never actually *called* `get_connection()` at module-load or startup — all its tests used `:memory:` fixtures. T04 is the first task that calls `get_connection()` inside `lifespan.startup_sweep()`. The bug is latent in T02; T04 turns it into an app-boot crash. Phase 0 DoD line "Fresh clone + first run produces `data/echolearn.db`" cannot be met without fixing this.

#### C2. `get_connection()` never applies `schema.sql`

- **File**: `backend/app/db/connection.py` — `_SCHEMA_PATH` is declared at line 12 but is not referenced anywhere in the module body (no `executescript`, no `IF NOT EXISTS`, no `schema_sql.read_text()`).
- `schema.sql` is **not** idempotent either — it uses `CREATE TABLE jobs (…)` and `CREATE INDEX idx_jobs_video`, both of which would raise if re-applied. (`specs/data-layer.md` line "Schema file is idempotent (`CREATE TABLE IF NOT EXISTS …`) and applied on first `get_connection()` call" — **neither** clause holds.)
- **Reproduction** (after C1 fix applied by creating the dir): `lifespan(app)` startup → `OperationalError: no such table: jobs` on `sweep_stuck_processing` because the DB file exists but is empty.
- **Fix options**:
  1. Convert `schema.sql` to `CREATE TABLE IF NOT EXISTS …` + `CREATE INDEX IF NOT EXISTS …`, and have `get_connection()` call `conn.executescript(_SCHEMA_PATH.read_text())` on first call.
  2. Lazily apply schema on first `get_connection()` call per process, with a module-level "applied" flag.
- **Severity note**: this is in the T02 scope per `specs/data-layer.md`. Review-t02 did not catch it because the `:memory:` test fixtures apply schema themselves in `conftest.py::_apply_schema`. T04's lifespan is the first production-path caller of `get_connection()`; the defect only manifests now. Either T04 lands a patch to `connection.py`, or T02 needs a follow-up patch.

### Important (should fix before T05; non-blocking if T05 schedules its own patch)

#### I1. Lifespan has no error handling — startup_sweep failure kills the entire app boot

- **File**: `backend/app/main.py:10-16`
  ```python
  runner = JobRunner()
  runner.startup_sweep()           # <— if this raises, FastAPI fails to start
  app.state.runner = runner
  ```
- After C1/C2 are fixed and the DB is usable in normal operation, there is still a question of what happens if `sweep_stuck_processing` raises for an unexpected reason (disk full, permissions, SQLite corruption). `lifespan` re-raises → uvicorn fails to bind → user sees a stack trace with no recovery.
- **Recommendation**: wrap `startup_sweep()` in `try/except Exception` and log at error level; the app can still serve read traffic and accept new jobs even if the sweep itself fails. The invariant "jobs records are NEVER left as perpetually processing" is eventually restored on the next successful boot. Alternatively, make this an explicit design decision documented in design.md §4 — but silent boot failure on a transient DB hiccup is not a good default.
- **Not blocker-level** because real production DB issues would also prevent new jobs from succeeding; but the current code has no diagnostic log and no graceful degradation. Two-line fix.

#### I2. `Pipeline` vs `JobRunner` use distinct DB connections — invariant "single SQLite transaction" for atomic publish is still honored, but it's worth locking down

- `_default_pipeline_run` opens its own connection; `JobRunner._get_repo()` opens a separate connection for `_fail_job` and `startup_sweep`. Writes from the two are serialized only by SQLite's writer lock (WAL), not by any Python-level coordination.
- This is fine today because `_run_job` calls `_pipeline_run_fn` and `_fail_job` sequentially inside one worker thread. But if a future change introduces a timeout/cancel path (`runner.cancel(job_id)` from a request thread while pipeline is still running), there would be two concurrent writers on different connections racing on the same `job_id`. The SQL conditional UPDATE protects `update_progress` but not `update_status` — a stale "completed" could clobber a fresh "failed" (or vice versa) if both arrive simultaneously.
- **Recommendation**: add a one-line comment in `runner.py` noting that `_fail_job` is currently called only after `_pipeline_run_fn` returns (sequential invariant), and that adding any concurrent cancel/timeout path will require rethinking the write ordering for `update_status`. No code change needed today.

### Minor (track, not block)

#### M1. Python per-connection shared lock is redundant and has two small defects

- **File**: `backend/app/repositories/jobs_repo.py:23-42`
- (a) `id(conn)` reuse across dead/new connections: `weakref.finalize` callbacks are gc-scheduled, not synchronous. Empirically reproduced: after `del c1; gc.collect()`, the finalizer did NOT run, `_conn_locks` retained the dead entry, and a new `c2 = sqlite3.connect(':memory:')` that happened to get the same id() inherited the old lock. Net effect is harmless (the reused lock is still a valid Lock object and nobody else is using it) but reasoning is easier to get wrong in future edits.
- (b) The module-level `_conn_locks` dict grows proportional to the number of transient connections opened through `get_connection()` minus those finalized. Under a `request → get_connection() → drop` pattern (which T05's router will likely adopt), the dict could grow indefinitely. In practice Python's gc will run, but latency between close and finalize is unbounded.
- (c) Given C2 will likely turn `get_connection()` into a schema-applier that runs on every call, and given the SQL conditional UPDATE already delivers monotonicity across distinct connections, the Python lock adds cognitive overhead without correctness value.
- **Recommendation**: remove `_conn_locks` / `_lock_for` / `weakref` imports. Replace `with self._lock:` in `update_progress` with the plain SQL-conditional path (the `strict` read-check-raise branch still needs to go somewhere; put it inside the method without a lock — under EL_TEST_STRICT, a reader seeing a lower current value before issuing the conditional UPDATE is still a bug worth surfacing, and the race window is acceptable in test mode). Roughly −30 lines net.
- **Defer to T05 or a small post-T04 patch**; not blocking T05's router work since correctness holds today.

#### M2. `JobRunner._get_repo()` creates a fresh connection per lazy call

- **File**: `backend/app/jobs/runner.py:121-126`
- First call opens and caches nothing; subsequent calls would reopen another connection if `_jobs_repo` is still None. In the lifespan path the code is called twice (once at startup_sweep, once per failure), so this happens at least 2-3× per process lifetime. Not a leak, but not elegant either.
- **Recommendation**: cache `self._jobs_repo` after first lazy construction (`self._jobs_repo = JobsRepo(get_connection())` inside `_get_repo`). One-line fix.

#### M3. `shutdown(wait=True)` can hang on stuck pipelines

- **File**: `backend/app/jobs/runner.py:75-77`
- `ThreadPoolExecutor.shutdown(wait=True)` has no timeout. If a pipeline's `whisper.transcribe()` is mid-HTTP-call to OpenAI when `lifespan` shutdown fires, uvicorn's graceful-shutdown deadline will elapse but this call blocks indefinitely.
- **Recommendation**: document the tradeoff explicitly (graceful drain preferred over abrupt kill). Or, if abrupt is acceptable, pass `cancel_futures=True` (Python 3.9+) which at least aborts queued futures, then rely on external SIGKILL / uvicorn's `graceful_timeout` for in-flight ones. Consider adding this to T09's DoD checklist ("shutdown completes within N seconds under simulated stuck pipeline").
- Not blocking T05.

#### M4. `sweep_stuck_processing` uses `RETURNING` (SQLite 3.35+)

- **File**: `backend/app/repositories/jobs_repo.py:145`
- Flagged in review-t02 L4. Dev SQLite is 3.38.2 (fine). Production deploys on Alpine-based Docker images can ship older libsqlite. Since `cursor.rowcount` after `UPDATE … WHERE …` works on every SQLite version, `RETURNING job_id` + `len(rows)` adds nothing. Recommend swap.
- Tech-debt note; not urgent.

#### M5. `update_status` accepts arbitrary `error_code` strings (carryover from review-t02 L1)

- Still not type-gated. `runner._fail_job` passes `exc.error_code` from `PipelineError` (free-form `str`) directly. The pipeline layer is the current gatekeeper. `Literal[...]` tightening can wait for T05 router schemas.

## Architecture review

- **Layering**: runner → pipeline → services → repositories is respected. Runner imports `JobsRepo` directly (for startup sweep + fail-job write-back) — acceptable for a lifecycle wrapper. No reverse dependencies.
- **DI**: `JobRunner` accepts `jobs_repo` and `pipeline_run_fn` callables; production path uses real modules via lazy construction. Tests inject fakes via constructor. ✓
- **Single-responsibility**: `runner.py` limits itself to (submit/sweep/shutdown) + exception translation. No business logic leaked in. ✓
- **200-line rule**: runner.py 136L, jobs_repo.py 182L, main.py 34L, pipeline.py 193L. All under. ✓
- **Lifespan**: startup → `runner.startup_sweep()`; shutdown → `runner.shutdown(wait=True)`. Runner exposed via `app.state.runner`. ✓ (pending C1/C2 fixes to make it callable.)

## QA review

- **Acceptance criteria from tasks.md T04**:
  - ✅ `JobRunner(max_workers=2, stale_threshold_sec=60.0)` signature present.
  - ✅ `submit()` runs `pipeline.run(job_id)` in executor, catches all exceptions, writes failed status.
  - ✅ `PipelineError` → `error_code` from exc; any other exception → `INTERNAL_ERROR`. Tested in `test_pipeline_error_sets_failed_with_error_code` + `test_unknown_exception_sets_internal_error`.
  - ✅ `startup_sweep()` delegates to `sweep_stuck_processing()`. Tested in `test_stale_processing_row_is_swept` (sweeps) and `test_fresh_processing_row_is_not_swept` (skips).
  - ✅ Default `stale_threshold_sec=60.0` verified by attribute inspection in `test_default_stale_threshold_is_60_seconds` — no wall-clock wait. ✓
  - ✅ Lifespan wired: startup → `startup_sweep()`; shutdown → `shutdown()`. **BUT C1/C2 prevent actual execution.**
  - ✅ `submit()` does not propagate exceptions: `test_submit_does_not_propagate_exceptions`.
  - ✅ Successful run does not overwrite status: `test_successful_run_does_not_override_status`.
  - ⚠️ "tests/integration/test_pipeline.py extended to cover: runner handles failure paths and records error codes" — in practice runner-level failure tests live in `test_runner.py` rather than extending `test_pipeline.py`. Equivalent coverage; spec letter not followed.
- **Edge cases covered in tests**: PipelineError, arbitrary Exception, success path, default threshold attribute, stale sweep (0.05s threshold + sleep 0.1s), fresh row untouched.
- **Edge cases NOT covered**:
  - `startup_sweep` running without any `processing` rows at all (DB has only `queued` / `completed`). Not strictly needed — `sweep_stuck_processing` unit tests in T02 cover that — but a lifespan-level smoke test wouldn't hurt.
  - `shutdown(wait=False)` with in-flight future. Spec allows `wait=True` default; future-cancel semantics unspecified.
  - `startup_sweep` raising (the I1 concern) — no test.
  - Concurrent `submit()` + `shutdown()` (submit after shutdown raises `RuntimeError` from executor; spec silent on this).
- **Test count**: 18 new/T04-relevant tests (cross-instance monotonicity 1 + runner 4 + sweep 3 + existing pipeline suite 11 that now exercise the integrated path). All passing.

## Security review

- **No new attack surface from T04.** Runner receives `job_id` from trusted sources (routers, tests); does not parse user input directly. `_fail_job` writes an error message that is `str(exc)` — same exposure as T03 (pipeline does the same thing), already reviewed.
- **`logger.warning("server restarted during processing")`**: no sensitive data. The log message is a fixed string; no user input interpolated. ✓
- **Executor thread safety**: `ThreadPoolExecutor(max_workers=2)` with `check_same_thread=False` on SQLite connections + SQL-conditional progress + WAL writer serialization — no injection or data-corruption path observed.
- **Weakref finalize + id(conn) dict**: no security implication (the dict is a private module-level cache; entries are anonymous lock objects). Memory growth is bounded by connection churn rate; see M1.
- **`get_connection()` path traversal**: `_DB_PATH` is derived from `__file__`, no user input. C1 is a correctness bug, not a security one.

## Recommendations

### Must-fix before T05 can proceed
1. **Patch `connection.py` for C1 + C2** in a single follow-up commit (e.g., `fix(db): apply schema and correct DB path for production startup`):
   - Drop one `.parent` call: `_DB_PATH = Path(__file__).parent.parent.parent / "data" / "echolearn.db"`.
   - Make `_DB_PATH.parent.mkdir(parents=True, exist_ok=True)` before `sqlite3.connect(path)`.
   - Convert `schema.sql` to `CREATE TABLE IF NOT EXISTS jobs (…)` / `CREATE INDEX IF NOT EXISTS idx_jobs_video` / same for `videos` / `segments`.
   - In `get_connection()`, after `PRAGMA foreign_keys=ON`, add `conn.executescript(_SCHEMA_PATH.read_text()); conn.commit()`.
   - Add a smoke test: `tests/integration/test_lifespan_boot.py` runs the `lifespan(app)` context against a fresh tmp_path DB path and asserts `app.state.runner` is attached without error.

### Should-fix in the same patch or T05
2. **I1** — wrap `startup_sweep()` in `try/except Exception` in `main.py` lifespan with a logger.error line.
3. **M2** — cache the lazy-constructed `JobsRepo` in `_get_repo()`.

### Defer / track
4. **M1** — remove `_conn_locks` / `_lock_for` / `weakref` machinery in a cleanup pass; SQL-conditional UPDATE is sufficient. Roughly −30 lines. Good candidate for T09 hygiene.
5. **M3** — document the `shutdown(wait=True)` hang tradeoff; consider `cancel_futures=True` + external graceful timeout.
6. **M4** — swap `RETURNING job_id` for `cursor.rowcount` to unlock older-SQLite deploy targets.
7. **M5** — tighten `error_code` to `Literal[…]` at the repo boundary during T05 router work.

## Verdict

**NEEDS_CHANGES.**

The T04 runner code itself is clean, well-tested, and architecturally correct — if considered in isolation, it would be APPROVED_WITH_NOTES (the Python-per-connection lock is redundant but safe; the deviation from review-t02 M1 is actually moot because the implementer applied the SQL conditional UPDATE in the preceding commit). The 133/0/0 test result genuinely validates the runner's behavioural contract.

However, the lifespan wiring is the first production-path invocation of `get_connection()`, and it exposes two pre-existing T02 defects (C1: wrong `_DB_PATH`; C2: `schema.sql` never applied) that crash the app at boot. These are T02 scope but T04 surfaces them — and T05 cannot reasonably build routers on top of a connection factory that can't open or populate the DB. They must be patched before T05 starts.

Estimated patch size: ~15 lines of code + one smoke test. Recommend a single `fix(db): …` commit on `change/phase0-refactor`, re-run `pytest` (should remain 133+ passed with the new lifespan test added), then T05 can proceed.
