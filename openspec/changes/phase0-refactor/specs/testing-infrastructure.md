# Capability — Testing Infrastructure

## Responsibilities
- Provide a TDD-ready testing foundation before any production code of this change is written.
- Offer fakes for expensive/external dependencies (Whisper, translator) with signatures identical to the real implementations.
- Give every task a consistent way to run its tests (`pytest`, `vitest`) and to verify observable UI behavior (`ui-verifier`).
- Keep tests hermetic: no network, no real DB file, no real browser except inside ui-verifier runs.

## Public interfaces

### Backend — pytest

```
backend/
  pytest.ini                (or pyproject [tool.pytest.ini_options])
  tests/
    conftest.py             (in-memory SQLite fixture, env overrides)
    fakes/
      whisper.py            (FakeWhisperClient)
      translator.py         (FakeTranslator)
    fixtures/
      whisper_normal.json
      whisper_empty.json
      whisper_allcaps_nopunct.json
    unit/
      test_segmenter.py
      test_repositories.py
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

The signatures of `transcribe` and `translate_batch` are the contract that the real clients in `services/transcription/whisper.py` and `services/translation/translator.py` must also satisfy.

### Frontend — Vitest

```
frontend/
  vitest.config.ts          (jsdom environment, setup file wired)
  src/
    test/
      setup.ts              (MSW server init + global beforeAll/afterEach/afterAll)
    features/
      player/hooks/
        useSubtitleSync.test.ts
        useAutoPause.test.ts
      jobs/hooks/
        useJobPolling.test.ts
    lib/
      youtube.test.ts
```

MSW handlers are defined per test; there are no default handlers in `setup.ts` beyond server lifecycle.

### ui-verifier
- Agent prompt: `.claude/agents/ui-verifier.md` (existing, not modified).
- Invocation: tasks that affect frontend behavior dispatch ui-verifier as a completion gate.
- Output: `docs/ui-verification/<task-id>.md` with PASS/FAIL + raw p95 numbers.

## Invariants
- **T01 comes first.** No production code of this change lands before this capability is in place.
- **Fakes mirror real signatures.** If a fake's method signature drifts from the real client's, both are wrong; tests must enforce the match.
- **Hermetic.** Unit and integration tests do not touch the network and do not require FFmpeg, real YouTube, real Whisper, or real translation.
- **Single-command run.** `pytest backend/tests` and `npm run test --prefix frontend -- --run` are the only commands needed to run the respective suites.
- **ui-verifier is authoritative for sync.** p95 thresholds are checked only via ui-verifier; Vitest verifies structural properties (binary search, no-rerender-on-same-index) but not timing.

## Non-goals
- Load / stress testing, performance benchmarking beyond ui-verifier's p95 metrics.
- Coverage gates (Phase 1+).
- Snapshot testing of rendered markup.
- Contract tests against real OpenAI endpoints.
