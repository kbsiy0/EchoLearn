# Review: phase0-refactor — T03 Pipeline rebuild (Whisper-only)

**Date**: 2026-04-17
**Reviewed**: Code (commit `ba26c34`)
**Verdict**: **APPROVED_WITH_NOTES**

## Executive Summary

T03 delivers the Whisper-only pipeline rebuild cleanly. 125/125 tests pass with 0 skips; the T01 conditional signature tests (`TestFakeWhisperVsRealClient::test_transcribe_signature_matches_real`, `TestFakeTranslatorVsRealClient::test_translate_batch_signature_matches_real`) have both flipped from SKIPPED → PASSED, confirming fake/real signature parity now holds mechanically. Segmenter algorithm matches design.md §3 verbatim. Atomic publish (Option A) is correctly implemented — translation results are held in memory until the 95→100 step. The regex validation in `download_audio` fires before any `Path` composition. No `youtube-transcript-api` in `requirements.txt`. Files all ≤ 200 lines except one pre-existing T01 test file (see M1).

Two production-path defects exist in how the pipeline translates real-client exceptions into `error_code` values (see I1). Neither blocks T04 because the current test suite uses `PipelineError`-raising fakes and passes; but they will surface the first time a real API call fails in production. Flagging as Important (not Critical) because (a) the fakes-based tests are green, (b) the pipeline still terminates, deletes audio, and marks the job `failed` — only the label is wrong, and (c) fixing is localized (one except clause per stage).

All four implementer-declared deviations are accepted as-is — each is well-justified and leaves the system cleaner.

## Implementer Deviations — Adjudication

1. **Split `test_pipeline.py` into `_golden.py` + `_failures.py`** — **ACCEPTED**. Both files land at 141/193 lines respectively, well under the 200-line rule. Naming convention is clear. Spec's `tests/integration/test_pipeline.py::test_*` references in tasks.md are nominal — what matters is the test names exist and pass.
2. **`Pipeline` constructor accepts `probe_fn` and `download_fn` callables** — **ACCEPTED**. Rationale (jobs table has no url column, probe URL is synthesized from video_id inside pipeline.run) is correct. Injection is via constructor DI, not module-level monkeypatch — matches the "clean" pattern the review rubric requires. Real module-level functions remain importable and are the default.
3. **`PipelineError` lives in `youtube_audio.py`** — **ACCEPTED_WITH_NOTE**. Works for now because `youtube_audio` is the first import dependency of `pipeline.py`. However, if later stages (whisper/translator) want to raise `PipelineError` directly, they'd need to import from `youtube_audio`, creating an awkward coupling (alignment/whisper/translation depending on transcription/youtube_audio just for an exception class). Suggest relocating `PipelineError` to `app/services/errors.py` in T04 or T05 as a small cleanup — not blocking for T03.
4. **`SubtitleSegment` + `JobCreate` legacy aliases in `schemas.py`** — **ACCEPTED**. `python -c "from app.routers.subtitles import router"` succeeds; the old router's imports resolve via aliases. Marked for T05 cleanup. No review concerns.

## Issues Found

### Critical
(none)

### Important

#### I1. Real-client runtime exceptions misclassify as `INTERNAL_ERROR` instead of `WHISPER_ERROR` / `TRANSLATION_ERROR`

- **Location**: `backend/app/services/pipeline.py:140-155` (the `except PipelineError / except ValueError / except Exception` chain).
- **Observation**: The except chain only produces `WHISPER_ERROR` when `segment(...)` raises `ValueError` (empty word list). Runtime failures from the real `WhisperClient.transcribe(...)` (per its docstring, "Raises: RuntimeError") and real `Translator.translate_batch(...)` ("Raises: RuntimeError") are `RuntimeError` subclasses, neither `PipelineError` nor `ValueError`, so they fall through to the generic `except Exception` branch and land as `error_code='INTERNAL_ERROR'`. This violates `specs/pipeline.md` Invariant "Error taxonomy" and design.md §4's taxonomy which reserves `INTERNAL_ERROR` for "uncaught exception, or processing row swept at startup." Whisper API failure is explicitly categorized as `WHISPER_ERROR` (retryable=yes), and translation API failure as `TRANSLATION_ERROR` (retryable=yes). Production behavior will differ from spec the first time an OpenAI call fails.
- **Evidence the tests don't catch this**:
  - `test_audio_deleted_on_whisper_failure` uses `FakeWhisperClient(words=RuntimeError("API error"))` but only asserts `job["status"] == "failed"` — it deliberately does NOT assert `error_code == "WHISPER_ERROR"`. So the defect is invisible to this test.
  - `test_audio_deleted_on_translation_failure` sidesteps the issue by making the fake raise `PipelineError("TRANSLATION_ERROR", ...)` — i.e. it tests a path that cannot occur with the real Translator (which raises `RuntimeError`, not `PipelineError`).
- **Recommendation**: Either (a) wrap the whisper and translate calls in pipeline.run with try/except that re-raises as `PipelineError("WHISPER_ERROR"/"TRANSLATION_ERROR", str(e))`; OR (b) make the real `WhisperClient` and `Translator` catch their internal exceptions and raise `PipelineError` themselves (consistent with the spec that says the error codes are "raised by Whisper" / "raised by Translator"). Option (b) is cleaner. Additionally, tighten the two failure tests to assert the specific `error_code`. Safe to defer to a small patch after T03 lands, but should be fixed before T04 integration tests extend to cover runner-level error propagation (T04 AC: "runner handles failure paths and records error codes").

### Medium

#### M1. `test_fake_signatures.py` exceeds the 200-line rule (219 lines)

- **Location**: `backend/tests/unit/test_fake_signatures.py`.
- **Observation**: Not touched in T03, authored during T01/T01-patch. But this file's conditional test classes (`TestFakeWhisperVsRealClient`, `TestFakeTranslatorVsRealClient`) first become load-bearing in T03 (they flipped from SKIPPED → PASSED on this commit), so it is appropriate to flag here. The file is 19 lines over the global 200-line cap.
- **Recommendation**: Split into `test_fake_signatures.py` (spec-stub comparisons) and `test_fake_vs_real_signatures.py` (real-module import + drift detection). Clean split — each is cohesive and well under 150 lines. Not urgent; can fold into a T01 follow-up patch or the T09 final-sweep remediation.

#### M2. Progress ladder integer checkpoints do not saturate design.md §2 ranges

- **Location**: `backend/app/services/pipeline.py:97-128`.
- **Observation**: Design.md §2 defines progress as ranges per stage (e.g., segmenter `65-70`, translation `70-95`). The implementation writes discrete values `5, 15, 45, 90, 95, 100`. The segmenter jump (45 → 90) skips the `65-70` range entirely, and the value `90` lands inside translation's `70-95` range. The user's brief frames these as "0→5→15→45→90→95→100" — i.e. pre-agreed discrete checkpoints — so this is not a blocker. But the design.md text still shows ranges, so any future reader diffing code against spec will be confused.
- **Recommendation**: Either (a) amend design.md §2 to show the agreed discrete checkpoints (add a "Per-stage end value:" line alongside the range); OR (b) add intermediate writes (e.g., segmenter writes 68 instead of 90). Option (a) is cheaper and already reflects the user's intent. Cosmetic drift; do during T09 docs pass.

#### M3. `test_malformed_video_id_rejected` tests the wrong layer vs tasks.md intent

- **Location**: `backend/tests/integration/test_pipeline_failures.py:128-135`.
- **Observation**: tasks.md T03 says this test should show "repo layer rejects bad video_id even if somehow reached." The actual test calls `download_audio("../../../etc/passwd")` and asserts `PipelineError(INVALID_URL)` — i.e. it verifies the SERVICE layer, not the REPO layer. The repo layer's regex enforcement IS tested separately in `test_repositories_videos.py::TestVideoIdRegexVideos` (and the jobs counterpart). Net coverage is fine — the repo layer is tested, and the service layer gets an additional test — but the named test doesn't do what the spec sentence said.
- **Recommendation**: Either rename the test (`test_malformed_video_id_rejected_at_download_layer`) or add a second test name at the repo layer (reusing the existing repo-layer regex test). Does not affect verdict.

### Low

#### L1. `FFMPEG_MISSING` detection only checks for `yt-dlp`, not `ffmpeg`

- **Location**: `backend/app/services/transcription/youtube_audio.py:110-112`.
- **Observation**: `download_audio` does `shutil.which("yt-dlp")` but not `shutil.which("ffmpeg")`. If yt-dlp is installed but ffmpeg is missing, the subprocess call will fail with a specific stderr from yt-dlp and be wrapped in `PipelineError("FFMPEG_MISSING", "Audio download failed: ...")` — the error code lands correctly, but the root cause is masked inside stderr text. Known project trap per `CLAUDE.md` ("ffmpeg 必要: Whisper 轉錄前要確認 `check_ffmpeg()`").
- **Recommendation**: Add an explicit `shutil.which("ffmpeg") is None` check alongside the yt-dlp one, with a more precise error message. Two lines of code.

#### L2. `pipeline.py` module-level `run(job_id)` instantiates real clients on every call

- **Location**: `backend/app/services/pipeline.py:171-187`.
- **Observation**: The module-level `run` creates a new `get_connection()`, `WhisperClient()`, `Translator()` per invocation. Fine functionally (both clients are cheap Python objects; the OpenAI client itself is lazy-imported inside each method). But it means repeated jobs pay object-construction overhead (negligible) and prevents swapping clients in production without going through the pipeline instance path. T04's runner should use `Pipeline(...).run(job_id)` with pre-constructed clients instead of the module-level shim — recommend deprecating the module-level `run` once T04 lands.

#### L3. Pipeline synthesizes `url` from `video_id` — `INVALID_URL` from probe is unreachable in practice

- **Location**: `backend/app/services/pipeline.py:99`.
- **Observation**: Because the pipeline reconstructs `url = f"https://www.youtube.com/watch?v={video_id}"` from a stored, regex-validated `video_id`, `probe_metadata` will never see a structurally-invalid URL via this path. The `INVALID_URL` branch inside `probe_metadata` is dead code on the normal pipeline path — it's only reachable by direct callers (currently none). Not wrong; just architecturally orphaned. The intake layer (T05) will own real URL validation. Document as-is, revisit if pipeline ever starts receiving raw user input.

## Architecture Review

- **Layering**: `pipeline.py` only imports from `services/*` and `repositories/*`. No direct DB access. No router/transport leaks. ✓
- **DI**: All three collaborator types (whisper client, translator client, probe/download callables) are constructor arguments with sensible defaults. Tests inject fakes; production uses real modules. No module-level monkeypatching in test code. ✓
- **Atomic publish**: `publish_video` in `videos_repo.py` uses `with self._conn:` to wrap (a) videos upsert, (b) segments DELETE, (c) segments INSERT executemany in a single SQLite transaction. `pipeline.run` only calls `publish_video` at the 95→100 step, after translation results are written back into the `segments` list in memory. `test_no_videos_row_on_early_failure` asserts no `videos` row on pre-publish failure. Option A invariant honored. ✓
- **Probe-before-download ordering**: `probe_metadata` raises `VIDEO_TOO_LONG` / `VIDEO_UNAVAILABLE` / `INVALID_URL` (line 63-83) before `download_audio` is ever called. `test_video_too_long_detected_before_download` asserts download is NEVER called via a sentinel list. ✓
- **Regex-before-Path**: `_VIDEO_ID_RE.match(video_id)` at `youtube_audio.py:109` runs before `_AUDIO_DIR / f"{video_id}.mp3"` at line 113. ✓
- **File sizes**: All new files ≤ 200 lines (largest: `pipeline.py` at 187). Legacy `subtitles.py` remains at 454 lines pending T05 deletion — acceptable.

## QA Review

- **Test count**: 125 passed, 0 failed, 0 skipped. Previously-SKIPPED T01 conditional tests (`test_transcribe_signature_matches_real`, `test_translate_batch_signature_matches_real`) are both PASSED — T03's acceptance criterion "T01 conditional tests flip to PASSED" is met. ✓
- **Segmenter test coverage** (spec's 8 required cases):
  1. Punctuation cut: `test_punctuation_cut_when_duration_gte_3s` (parametrized on `.`, `!`, `?`) ✓
  2. Silence cut: `test_silence_gap_cut_when_gap_gte_0_7s_and_duration_gte_3s` ✓
  3. 15s hard cap: `test_15s_hard_cap`, `test_15s_hard_cap_regardless_of_punctuation` ✓
  4. Empty input raises `ValueError`: `test_empty_raises_value_error` ✓
  5. Single token: `test_single_token_emits_one_segment` ✓
  6. All-caps-no-punctuation: covered inside the 15s cap tests (WORD0..WORDn fixtures) ✓
  7. Leading-space tokens: `test_leading_space_tokens_normalized`, `test_comma_token_leading_space` ✓
  8. Quote-trailing punctuation: `test_quote_trailing_punctuation_period`, `test_quote_trailing_punctuation_question`, `test_curly_quote_trailing_punctuation` ✓
- **Golden pipeline coverage**: `videos` row written, `segments` in order, `jobs.status=completed`, `progress=100`, audio deleted — all four assertions have dedicated tests in `test_pipeline_golden.py`. ✓
- **Failure paths**: whisper-failure audio cleanup, translation-failure audio cleanup, video-too-long short-circuit (with download-NOT-called assertion), malformed video_id rejection (service layer — see M3), empty whisper output → WHISPER_ERROR via ValueError mapping, no videos row on early failure. ✓
- **Fake injection style**: constructor DI across the board. No module-level monkeypatch in any integration test. ✓
- **Gap**: failure tests don't assert the specific `error_code` for whisper/translator runtime failures — hiding I1.

## Security Review

- **Shell injection**: `subprocess.run([...], shell=False)` (argv-list form) throughout `youtube_audio.py`. No f-strings into shell. ✓
- **Path traversal**: `video_id` regex-validated before any Path composition (both in `download_audio` and in both repositories). Malformed `video_id` (e.g., `"../../../etc/passwd"`) raises before touching the filesystem — verified by test. ✓
- **Subprocess timeouts**: both yt-dlp invocations bound (probe=60s, download=300s). No unbounded child processes. ✓
- **Regex DoS**: `^[A-Za-z0-9_-]{11}$` is a simple character-class quantifier, not vulnerable to catastrophic backtracking. ✓
- **Secrets**: `OPENAI_API_KEY` read via `os.getenv(...)` with `""` default; `import openai` is lazy inside each method, so tests without the env var set don't raise at class instantiation. ✓
- **`youtube-transcript-api` removal**: grep of `backend/requirements.txt` and `pyproject.toml` → not listed. Package is still importable in the current dev env (leftover install) but a fresh `pip install -r requirements.txt` will not bring it in. Legacy `transcript.py` and old `subtitles.py` still import it; that code will be deleted in T05. ✓
- **Stack traces not leaked**: pipeline catches exceptions and writes `str(exc)` as `error_message`. Spec's HTTP 400 `error_message` sanitization requirement is a T05 router concern, not T03's; but pipeline doesn't leak full tracebacks into the DB either — `str(exc)` is short and opaque. ✓

## Recommendations

- **Before T04 starts** (blocking for clean T04 runner-error-propagation tests): fix I1 by wrapping whisper and translator calls in try/except → `PipelineError("WHISPER_ERROR"|"TRANSLATION_ERROR", ...)`, and tighten `test_audio_deleted_on_whisper_failure` / `test_audio_deleted_on_translation_failure` to assert the specific error_code. ~10 lines of change.
- **Optional (T04 or T05 cleanup)**: relocate `PipelineError` to `app/services/errors.py` to break the `alignment` / `translation` dependency on `transcription/youtube_audio.py` once those stages start raising `PipelineError` directly (they'll need to after I1 fix).
- **Before T09**: amend design.md §2 to show discrete checkpoints alongside ranges (M2), or add intermediate progress writes. Also split `test_fake_signatures.py` (M1).
- **Low-priority**: add explicit `ffmpeg` binary check (L1), deprecate module-level `pipeline.run` once T04 lands (L2), either document or remove the unreachable `INVALID_URL` branch inside `probe_metadata` relative to the main pipeline call path (L3).

T03 is approved to proceed to T04. None of the above issues block T04 dependencies (T04 needs pipeline.run to exist, advance progress, set terminal status, and delete audio — all of which work today). I1 should be patched before the pipeline sees real API traffic, which is before Phase 0 DoD; fixing early avoids rework in T04's error-propagation test suite.
