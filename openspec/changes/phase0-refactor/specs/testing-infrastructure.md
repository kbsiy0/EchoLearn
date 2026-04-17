# Capability — Testing Infrastructure

## Responsibilities
- Provide a TDD-ready testing foundation before any production code of this change is written.
- Offer fakes for expensive/external dependencies (Whisper, translator) with signatures identical to the real implementations.
- Give every task a consistent way to run its tests (`pytest`, `vitest`) and to verify observable UI behavior (`ui-verifier`).
- Keep tests hermetic: no network, no real DB file, no real browser except inside ui-verifier runs.
- Expose configurability (stale thresholds, test-strict flags) so production-default behavior can be tested without wall-clock waits.

## Public interfaces

### Backend — pytest

```
backend/
  pytest.ini                (or pyproject [tool.pytest.ini_options])
  tests/
    conftest.py             (in-memory SQLite fixture, env overrides, EL_TEST_STRICT flag)
    fakes/
      whisper.py            (FakeWhisperClient)
      translator.py         (FakeTranslator)
    fixtures/
      whisper_normal.json
      whisper_empty.json
      whisper_allcaps_nopunct.json
      whisper_leading_space_tokens.json   (for whitespace normalization rule)
      whisper_quote_trailing_punct.json   (for ." / .” / ?' cut behavior)
    unit/
      test_segmenter.py
      test_repositories.py
      test_fake_signatures.py             (inspect.signature diff: fakes vs real clients)
      test_sanity.py                      (test_truthy — guarantees non-empty collection for T01)
    integration/
      test_pipeline.py
      test_jobs_api.py
      test_startup_sweep.py
```

Fake contracts:
```python
class FakeWhisperClient:
    def __init__(self, words: list[Word] | Exception): ...
    def transcribe(self, audio_path: Path) -> list[Word]: ...

class FakeTranslator:
    def __init__(self, mapping: dict[str, str] | Exception): ...
    def translate_batch(self, texts_en: list[str]) -> list[str]: ...
```

The signatures of `transcribe` and `translate_batch` are the contract that the real clients in `services/transcription/whisper.py` and `services/translation/translator.py` must also satisfy. This contract is mechanically verified by `test_fake_signatures.py` using `inspect.signature`.

### Frontend — Vitest

```
frontend/
  vitest.config.ts          (jsdom environment, setup file wired)
  src/
    test/
      setup.ts              (MSW server init + global beforeAll/afterEach/afterAll)
    features/
      player/hooks/
        useYouTubePlayer.test.ts         (lifecycle via IFrame API mock)
        useSubtitleSync.test.ts          (binary-search boundaries)
        useAutoPause.test.ts
      jobs/hooks/
        useJobPolling.test.ts            (interval + terminal-stop + cancel-on-unmount)
    lib/
      youtube.test.ts
```

MSW handlers are defined per test; there are no default handlers in `setup.ts` beyond server lifecycle.

### Configurability handles
- **`sweep_stuck_processing(older_than_sec)`** and `JobRunner(stale_threshold_sec=…)` are parameters — tests pass tiny thresholds (e.g., `0.1s`) to verify sweep behavior without wall-clock waits.
- **`EL_TEST_STRICT=1`** (set by the conftest fixture) makes `update_progress` raise `AssertionError` on attempted regression. Production paths without this flag log a WARN.
- **In-memory SQLite** avoids filesystem interaction in unit/integration tests.

### ui-verifier
- Agent prompt: `.claude/agents/ui-verifier.md` (existing, not modified).
- Invocation: tasks that affect frontend behavior dispatch ui-verifier as a completion gate.
- Output: `docs/ui-verification/<task-id>.md` with PASS/FAIL + raw p95 numbers.

## Invariants
- **T01 comes first AND ships real tests.** At minimum one real test per hook that T06 will move: `useJobPolling` (interval + terminal-stop), `useYouTubePlayer` (lifecycle mock), `useSubtitleSync` (binary-search boundaries). No production code of this change lands before this capability is in place.
- **Fakes mirror real signatures.** If a fake's method signature drifts from the real client's, both are wrong; `test_fake_signatures.py` enforces the match via `inspect.signature` diff.
- **Hermetic.** Unit and integration tests do not touch the network and do not require FFmpeg, real YouTube, real Whisper, or real translation.
- **Single-command run.** `pytest backend/tests` and `npm run test --prefix frontend -- --run` are the only commands needed to run the respective suites.
- **ui-verifier is authoritative for sync.** p95 thresholds are checked only via ui-verifier; Vitest verifies structural properties (binary search, no-rerender-on-same-index) but not timing.
- **Thresholds are parameters, never constants-in-code.** Any time-based threshold that participates in test assertions (stale sweep, polling interval) is injectable.

## Non-goals
- Load / stress testing, performance benchmarking beyond ui-verifier's p95 metrics.
- Coverage gates (Phase 1+).
- Snapshot testing of rendered markup.
- Contract tests against real OpenAI endpoints.
