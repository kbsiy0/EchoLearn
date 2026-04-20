# Review: phase0-refactor / T05 — Router split + cutover

**Date**: 2026-04-17
**Reviewed**: Code (commit `8415566`)
**Verdict**: **NEEDS_CHANGES**

## Scope
Commit moves the monolithic `routers/subtitles.py` (455 lines) into `routers/{jobs,subtitles,videos}.py`, adds an HTTPException handler in `main.py` to flatten structured `detail` dicts, deletes `app/cache/`, and moves three helper functions to `services/alignment/word_timing.py`. 156 pytest tests pass locally.

---

## Issues Found

### 🔴 Critical

**C1. `GET /api/subtitles/{video_id}` returns HTTP 500 when `video_id` is malformed.**
`routers/subtitles.py::get_subtitles` passes `video_id` directly to `VideosRepo.get_video`, and `videos_repo._validate_video_id` raises `ValueError` for anything not matching `^[A-Za-z0-9_-]{11}$`. No try/except, no path validator → FastAPI surfaces the bare exception as 500 Internal Server Error. Confirmed live:
```
GET /api/subtitles/someVideoIdX  → 500 Internal Server Error
GET /api/subtitles/short         → 500 Internal Server Error
```
- Violates `specs/jobs-api.md` invariant **"404 contracts. Unknown `job_id` and not-yet-completed `video_id` both return HTTP 404."**
- Violates the safety principle of not surfacing exception internals on public endpoints — while `TestClient` hid the body, `raise_server_exceptions=True` in the tests means the test suite is blind to this path today (no test asserts shape of the 500 body).
- Same issue latent in `GET /api/subtitles/jobs/{job_id}` only if `jobs_repo.get` validates — it doesn't, so that path is fine; but the symmetry hole on subtitles is real.

Fix options: (a) validate `video_id` at the router with a Pydantic `Path(..., pattern=...)`, returning 404 on mismatch, or (b) `except ValueError → raise HTTPException(404)`. Either needs a regression test.

**C2. Test coverage for the 500 path is absent.**
`test_jobs_api.py` tests 400 and 404 for known cases, but there is no test for `GET /api/subtitles/<malformed>` or for malformed `job_id`. Combined with `raise_server_exceptions=True` on the TestClient fixtures, any 500 in production would have passed CI silently. Must land alongside the C1 fix.

### 🟡 Medium

**M1. Synthetic cache-hit job is not persisted — deviates from `design.md` Section 4.**
Design says: *"If a videos row exists, `POST` inserts a synthetic completed job and returns immediately."* Implementation in `jobs.py::create_job` generates a `uuid.uuid4()` and returns it inline without writing to the `jobs` table. Polling that `job_id` returns 404. Works in practice only if clients honor the POST body's `status == 'completed'` and skip polling — but that behavioral coupling is not pinned in the spec. Either: (a) insert the row so polling works, or (b) amend the design wording to say "returns a synthetic completed response (not persisted); clients MUST NOT poll when `status == 'completed'` in the POST body".

**M2. D1 (word_timing.py move): module is dead code in the Whisper-only pipeline.**
`normalize_segments`, `estimate_word_timings`, `assign_words_to_segment` are imported only by `tests/test_segment_merge.py`. The T03 pipeline uses `services/alignment/segmenter.py` exclusively — grep confirms zero production callers of the moved functions. Keeping them here preserves old tests that no longer describe production behavior, and the filename `word_timing.py` overlaps in concept with `segmenter.py`'s own word handling — readers will be unsure which is authoritative. Acceptable short-term (the move itself is better than the router keeping them), but schedule a follow-up: delete `word_timing.py` + `test_segment_merge.py` together in T08 data-cleanup, OR convert `test_segment_merge.py` into a regression harness against `segmenter.py`.

**M3. D2 (HTTPException handler): overrides ALL HTTPExceptions, not only the structured-detail case.**
`http_exception_handler` is registered on `FastAPIHTTPException` (superset). For string-detail exceptions it reconstructs the default `{"detail": <str>}` envelope manually. This works (verified: `{'detail': 'Job not found'}`) but means any future FastAPI change to the default 404/405/401 body formatting will silently diverge. Recommend narrowing the handler: `if isinstance(exc.detail, dict): return JSONResponse(...); else: raise exc` (or delegate to `fastapi.exception_handlers.http_exception_handler`). Low-risk today, but the latent divergence risk is not obvious to future readers.

**M4. Orphaned legacy module `app/services/transcript.py` still imports `youtube_transcript_api`.**
The file is no longer imported anywhere in `app/` (grep confirms no callers), and `youtube_transcript_api` was removed from `requirements.txt` in T03, so any attempt to import `app.services.transcript` will raise `ModuleNotFoundError` at import time. This is not a T05 regression (it predates the task) but T05's cutover spec says **"This is the cutover point — old router goes away"** — the symmetric cleanup of dead service modules belongs here or explicitly deferred to T08. Flag now so it doesn't slip.

**M5. HTTP status distinction (201 vs 200) is undocumented.**
Implementation: new job → 201, dup-submit → 200, cache-hit → 200. Tests assert the specific codes but neither `specs/jobs-api.md` nor `design.md` document the 201/200 split. Either add a one-line note ("201 when job row created, 200 when returning existing/synthetic") or normalize to 200/201 consistently.

### 🟢 Low

**L1. `jobs.py` is 146 lines — approaching the 200-line ceiling.** Within rules now; future growth (auth, rate-limit, retry policy) will push it over. Ignore for T05, flag for T09 DoD scan.

**L2. `_safe_error_message` uses a substring blacklist.** Works for today's `url_validator` error messages, but future error-raising code paths could include safe text that contains `Error(` (e.g. "URL Encoding Error(n)"). The safer pattern is an allowlist (map known exception types to a fixed set of safe messages). Not exploitable right now because only `validate_youtube_url` feeds it, and its messages are all author-controlled.

**L3. `test_error_message_has_no_stack_trace` is weak.**
The assertion `"Error:" not in msg or msg.startswith("INVALID_URL")` short-circuits when the message happens to start with `INVALID_URL` — which the implementation strips before passing to `_safe_error_message`. In practice the message is `"Could not parse URL"`, so the test never exercises the `Error:` branch. Tighten: assert strict equality against a known-safe string like `"Invalid YouTube URL"` or `"Could not parse URL"`.

**L4. `FakeRunner.shutdown` signature is `shutdown(self, wait: bool = True)` but `JobRunner.shutdown` signature is `shutdown()` in the public spec — the fake exposes an extra kwarg.** Harmless but surfaces if anyone introspects via `Protocol`.

**L5. `videos.py::get_db_conn` and `subtitles.py::get_db_conn` and `jobs.py::get_db_conn` are three copies of the same function.** Minor DRY violation; factor into `app/routers/deps.py` when convenient. Ignore for T05.

**L6. `from fastapi.exceptions import HTTPException as FastAPIHTTPException  # noqa: E402`** is placed below `app = FastAPI(...)` — the `noqa` admits the lint violation instead of moving the import up. Cosmetic; move to top and drop the `noqa`.

---

## Architecture Review

The three-router split is clean: `jobs.py` handles POST/GET /api/subtitles/jobs, `subtitles.py` handles GET /api/subtitles/{video_id}, `videos.py` handles GET /api/videos. Responsibilities respect the layer model — routers use repositories; no cross-layer shortcuts. `cache/` directory deletion confirmed (`ls backend/app/cache` → "No such file or directory"). CORS middleware preserved verbatim at `main.py:24-30` with `allow_origins=['http://localhost:5173']` — not `*`, and evil origin returns 400 without ACAO header (verified). `main.py` no longer holds any in-memory job dict. Overall T05's architectural goal is met.

The only architectural concern is **D1**: `services/alignment/word_timing.py` now holds three functions that no production code calls (only the old test imports them). The alignment module now contains two parallel segmenters — `segmenter.py` (the T03 replacement) and `word_timing.py::normalize_segments` (the pre-T03 helper). This is tolerable as a transition artifact but should not survive into Phase 1.

## QA Review

`pytest` full run: **156 passed, 0 failed, 0 skipped** in 1.41s. Integration tests cover: new submission, dup-submit returns same job_id, cache-hit short-circuits with `runner.submit` NOT called (verified via `FakeRunner.submitted` spy), retry after failure, 404 on unknown job, 404 on unreached subtitles (only with valid-shape video_id), HTTP 400 on invalid URL with sanitized message, CORS preserved.

Gaps:
- **C1/C2**: malformed `video_id` in `GET /api/subtitles/{video_id}` is uncovered and hits a 500. Must add a test like `test_subtitles_malformed_video_id_returns_404`.
- **M1**: no test verifies `GET /api/subtitles/jobs/<synthetic_cache_hit_id>` behavior — if the spec is preserved as "inserts", this should 200; if amended, the test should assert that clients do not need to poll.
- **L3**: sanitize test has a short-circuit that can pass trivially.

Dup-submit and cache-hit runner-spy coverage is solid. CORS test uses real TestClient with `Origin: http://localhost:5173` — good.

## Security Review

- `url: constr(max_length=2048)` — enforced via Pydantic; verified 3000-char URL returns 422, stops before any business logic.
- CORS is correctly restricted to `http://localhost:5173`; evil origin does not get ACAO header.
- `video_id` regex defense in depth: enforced at `url_validator.py`, at `jobs_repo`, and at `videos_repo`. Triple-layer — good.
- `_safe_error_message` substring blacklist catches `Traceback`, `File "`, `ValueError`, `Exception`, `Error(`; not bypass-proof but OK for an author-controlled error source. Flag **L2** for robustness.
- **C1 is a security-adjacent concern**: uncaught `ValueError` at a public endpoint leaks a stack trace in dev mode and is observable as 500. With `raise_server_exceptions=True`, tests never see the body but a real deployment behind uvicorn exposes the default Starlette 500 page (safe, no stack), however if debug mode ever toggles on, the stack trace would include the `video_id` regex details. Closing this is mainly about spec compliance (404 contract) but the defense-in-depth angle matters.
- `HTTPException` handler does NOT expose internal paths or stack traces — `detail` is author-controlled in all current callers.

## Recommendations

Before T06 can start:
1. **C1 fix (blocker):** validate `video_id` at `routers/subtitles.py` OR catch `ValueError` → 404. Add matching regression test.
2. **M1 resolution (blocker):** either persist the synthetic cache-hit job OR amend the spec + add a test that pins the new contract; don't leave it ambiguous — T06 will build `useJobPolling` against this contract.
3. **M3 narrowing (recommended):** tighten `http_exception_handler` to only handle dict-detail; delegate string case to FastAPI default. Add test for 404 body shape so future regressions are caught.

Defer to T08 or a small follow-up patch:
4. **M2 / M4:** remove dead `word_timing.py` + `test_segment_merge.py`, delete `app/services/transcript.py`.
5. **L1–L6** are backlog items.

---

## Deviation Decisions

- **D1 (word_timing.py move)**: **accepted with reservation**. Move itself is correct — router should not hold business logic. However the moved functions are not used by the Whisper-only pipeline; they survive only to keep old tests passing. See M2. Not a blocker.
- **D2 (HTTPException handler)**: **accepted with required narrowing (M3)**. Current impl works for all existing 400/404 cases; verified via live TestClient probe. But registering on the entire HTTPException type reproduces FastAPI's default envelope by hand, which risks silent divergence. Narrowing is a 3-line change.

## pytest summary
```
156 passed in 1.41s
```

