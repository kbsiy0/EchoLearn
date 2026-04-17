# Capability — Pipeline

## Responsibilities
- Orchestrate end-to-end subtitle production for a video: audio acquisition → transcription → segmentation → translation → persistence.
- Advance `jobs.progress` monotonically through the defined ladder.
- Translate failures from any stage into a canonical `error_code` + `error_message` on the job row.
- Clean up per-job ephemeral audio files on both success and failure.

## Public interfaces

```python
# backend/app/services/pipeline.py
def run(job_id: str) -> None: ...
```

The runner owns invocation; `pipeline.run` never creates threads of its own.

Internal collaborators (each a separate module, each unit-testable with its fake):

```python
# backend/app/services/transcription/youtube_audio.py
def download_audio(video_id: str, url: str) -> Path: ...
#   raises FFMPEG_MISSING, VIDEO_UNAVAILABLE, VIDEO_TOO_LONG

# backend/app/services/transcription/whisper.py
class WhisperClient:
    def transcribe(self, audio_path: Path) -> list[Word]: ...
#     Word = {"text": str, "start": float, "end": float}

# backend/app/services/alignment/segmenter.py
def segment(words: list[Word]) -> list[Segment]: ...
#   raises ValueError("no speech detected") when words is empty

# backend/app/services/translation/translator.py
class Translator:
    def translate_batch(self, texts_en: list[str]) -> list[str]: ...
```

## Invariants
- **Single time base.** Every `Segment.start`, `Segment.end`, and per-word `start`/`end` originates from the Whisper word stream. No other timing source is mixed in.
- **Progress is monotonic.** Each stage only advances `progress`; it never regresses, and each stage emits at least one update within its assigned range.
- **Atomic publish.** A video and its segments are either both fully persisted or not persisted at all. No partial `segments` rows are left if translation fails midway.
- **Audio cleanup is unconditional.** The audio file for a job is deleted whether the job completes, fails, or throws.
- **Error taxonomy.** Every failure path resolves to exactly one of: `INVALID_URL`, `VIDEO_UNAVAILABLE`, `VIDEO_TOO_LONG`, `FFMPEG_MISSING`, `WHISPER_ERROR`, `TRANSLATION_ERROR`, `INTERNAL_ERROR`.

## Non-goals
- Streaming or incremental publication of segments as they are produced (Phase 1).
- Retry logic inside the pipeline (caller/runner resubmits a new job if the user retries).
- Multi-language targets (Phase 2+).
- Any use of `youtube-transcript-api` — removed.
