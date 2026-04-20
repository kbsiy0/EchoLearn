# Review: phase0-refactor T08 — Data cleanup + audio orphan sweep

**Date**: 2026-04-18
**Commit**: `09f9732` on `change/phase0-refactor`
**Reviewed**: Code vs spec (stage 2)
**Verdict**: **APPROVED_WITH_NOTES**

## Issues Found

### 🟡 Minor

1. **Acceptance criterion "removed within 1 second of app start" not asserted via timing.**
   `tasks.md:274` reads *"integration test: files with no matching `processing` job are removed within 1 second of app start."* The four `TestAudioOrphanSweep` cases assert correctness by calling `runner.startup_sweep()` directly, never through the FastAPI lifespan, and there is no `time.time()` bound. This is acceptable — `_sweep_audio_orphans` is a synchronous local `glob` + `unlink` loop, trivially sub-millisecond for any realistic directory — but the verdict-bearing words "within 1 second of app start" are not verified against an actual clock. Recommend a single `time.perf_counter()` bound around `startup_sweep()` in one of the tests, or explicit note in the test docstring that the operation is synchronous on the startup thread.

2. **Production default `Path("data/audio")` is CWD-relative; silently no-ops if uvicorn runs from the wrong dir.**
   `runner.py:29` `_DEFAULT_AUDIO_DIR = Path("data/audio")` mirrors `youtube_audio.py:26` `_AUDIO_DIR = Path("data/audio")`, so the convention is consistent and the orphan cleanup stays aligned with downloads. The downside: `_sweep_audio_orphans` early-returns on `if not self._audio_dir.exists()` (runner.py:94), so if uvicorn is launched outside `backend/` the sweep quietly does nothing. Not introduced by this task — inherited from `youtube_audio.py` — but worth logging a single `logger.info` when the dir is missing so operators can spot a misconfigured launch. Not blocking.

3. **Sweep classifies on "no active queued/processing job" but docstring says "no matching processing job".**
   `runner.py:89` says *"no matching active (queued/processing) job"*, but the acceptance criterion (`tasks.md:274`) and design (`design.md:315`) both say *"no corresponding `processing` job"*. Using `find_active_for_video` (which filters `status IN ('queued','processing')`) is actually the safer choice — a freshly-queued job that hasn't started downloading yet still shouldn't have its mp3 deleted — but the divergence from spec wording should be either (a) resolved by tightening the docstring + spec to say "queued or processing", or (b) noted in the task DoD. Prefer (a); the behavior is correct.

4. **No test for the `OSError` branch on `mp3.unlink()`.**
   `runner.py:100-102` swallows `OSError` with a `logger.warning`. No test covers this path. Minor, but a `monkeypatch` forcing `Path.unlink` to raise would cost two lines and prove the sweep doesn't abort on one bad file.

### 🟢 Low

5. **`_sweep_audio_orphans` takes `repo` as argument but `self._get_repo()` is available.**
   `runner.py:85` `self._sweep_audio_orphans(repo)` — passing the repo rather than reading `self._get_repo()` is fine (avoids a second lookup) but slightly inconsistent with `_fail_job` which fetches via `self._get_repo()`. Style nit only.

## Architecture Review

- **Location of the sweep.** Adding `_sweep_audio_orphans` to `JobRunner` is the right call. Design doc (`design.md:315`) bundles "audio cleanup" alongside the startup orphan-job sweep conceptually, and `JobRunner.startup_sweep()` is already the single entry point invoked from the FastAPI lifespan (`main.py:17-18`). A new `AudioCleanup` class would be over-engineering; a standalone helper in `services/` would force a second lifespan call. The current design keeps startup wiring to a single method on a single object.
- **Lifespan wiring.** `main.py:17` creates `JobRunner()` with no args → default `audio_dir=Path("data/audio")`, matches `youtube_audio.py` convention. The sweep runs synchronously on the startup thread, blocking app readiness — correct for a small `glob` + `unlink` loop.
- **File size.** `runner.py` is 161 lines (`wc -l`), comfortably under the 200-line ceiling from project CLAUDE.md.
- **`audio_dir` injection.** Constructor param with `None` sentinel + module-level default is the same pattern used for `jobs_repo` and `pipeline_run_fn`. Consistent and testable.
- **`import sqlite3` removal.** That import was a dead leftover from earlier revs of `runner.py`; removing it is proper cleanup, not unrelated scope. Confirmed via `git diff` — it was imported but never used after T05.

## QA Review

- **Four tests cover:** (1) orphan with no DB row, (2) orphan with `completed` job, (3) retention when job is `processing`, (4) mixed active+orphan set. That matches the four cases you'd want; the 4th is a "mixed-files" smoke test proving both branches coexist in one run.
- **Isolation.** All four tests use `tmp_path` for `audio_dir` and the `db_conn` fixture for DB. None of them touch real `backend/data/audio/`. Clean.
- **Full suite green.** `pytest` → `164 passed in 0.78s`. No regressions from earlier tasks.
- **Missing edge cases** (documented above as Minor issues):
  - No timing bound on the "within 1 second" criterion.
  - No `OSError` branch coverage.
  - No test for `audio_dir` pointing at a non-existent directory (covered by the `if not self._audio_dir.exists()` early return on runner.py:94 but not asserted).
  - No test for a non-11-char or non-video-id-shaped filename landing in the dir — but since `_VIDEO_ID_RE` is never applied before `find_active_for_video` (see Security note), a malformed filename falls through to "no active job" and gets deleted. That is arguably correct behavior (it's an orphan!) but worth confirming intentional.

## Security Review

- **Path traversal.** `self._audio_dir.glob("*.mp3")` cannot return entries outside `self._audio_dir` — `glob` does not cross directory boundaries, and POSIX/APFS do not allow `/` in a single filename component. `mp3.unlink()` operates on the `Path` returned by `glob`, always rooted at the (test-provided or production) audio dir. No traversal risk.
- **video_id validation before DB query.** `find_active_for_video` (`jobs_repo.py:174-182`) does NOT call `_validate_video_id` on its input, while `create`/`update_status` do. The sweep extracts `mp3.stem` and hands it to `find_active_for_video`. SQL is parameterized, so this is not an injection vector, and a non-matching stem simply returns `None` → file unlinked as orphan. Intentional or not, this is safe. **Recommendation:** document in a code comment that malformed filenames in `data/audio/` are treated as orphans and deleted, so a future reader doesn't mistake the missing validation for a bug.
- **Race condition on `unlink`.** A pipeline worker thread cannot be mid-download when `startup_sweep` runs — `startup_sweep` executes synchronously in the lifespan before `yield`, i.e. before any request handler can enqueue work. No TOCTOU risk against live downloads.
- **False-positive removal of pre-processing job's audio.** The sweep retains files whose video_id matches a `queued` OR `processing` row (via `find_active_for_video`). A job whose row exists but has not yet downloaded its mp3 is safe — there is no file to sweep. A job that finished download but crashed before status update to `completed` leaves a `processing` row → retained. If the stale-sweep path in the same `startup_sweep()` call flips that row to `failed` just moments earlier, the mp3 would then be orphaned on the NEXT startup, not this one — because the audio sweep reads the repo AFTER `sweep_stuck_processing` runs. **Check:** `runner.py:74-85` confirms stale sweep runs first (line 74), audio sweep after (line 85). This means a stale `processing` row has already been flipped to `failed` by line 85, and its mp3 will be removed in THIS sweep, not the next one. That is correct and consistent with the spec.
- No hardcoded credentials or secrets. Nothing logged contains user data beyond `mp3.name` (a video_id).

## Recommendations (priority order)

1. **Add a timing bound to one sweep test** (e.g. `assert elapsed < 1.0`) to literally verify the "within 1 second" criterion from `tasks.md:274`. Keep it as one extra assertion, not a new test case.
2. **Reconcile sweep docstring vs. spec wording**: either update `runner.py:89` to match `design.md:315` ("no matching processing job") AND change behavior to query only `status='processing'`, or tighten the spec to say "queued or processing" and keep the current (safer) behavior. The latter is preferable — retaining a just-queued job's audio is the right call.
3. **Add a single test** that monkeypatches `Path.unlink` to raise `OSError` and asserts the sweep logs a warning and continues processing the remaining files. Two lines.
4. **Document filename-to-video_id semantics** in a comment on `_sweep_audio_orphans` — specifically that non-video-id-shaped stems fall through to `find_active_for_video`, match nothing, and are deleted. Prevents a future reader from "fixing" the missing validation.
5. (Low) Log `logger.info` once when `self._audio_dir` doesn't exist at startup, so misconfigured launches are visible in logs instead of silent no-ops.

## Scope check

- Files changed: `backend/app/jobs/runner.py`, `backend/tests/integration/test_startup_sweep.py`, and the on-disk deletion of `backend/data/cache/OEa0YxtOKnU.json` (which was already gitignored → no diff entry). No files outside T08 scope were modified. `backend/app/cache/` genuinely never existed (confirmed via git log). `backend/data/cache/` is gitignored at `.gitignore:28`. DoD items 1, 2, 3, 4, 5 all satisfied; item 3's "within 1 second" is proven by construction rather than by clock, flagged above.

---

**Verdict**: APPROVED_WITH_NOTES — code is correct, tests green, scope clean. The four Minor items (timing assertion, docstring/spec reconciliation, OSError branch test, stem-validation comment) are polish and do not block T09.
